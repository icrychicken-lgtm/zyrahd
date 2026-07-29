"""Discord OAuth2 login with state and guild-membership validation."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode, urlparse

import requests
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from config import settings
from dashboard.app import limiter
from dashboard.decorators import current_user

auth = Blueprint("auth", __name__)
DISCORD_API = "https://discord.com/api/v10"


def _safe_next(value: str | None) -> str:
    if not value:
        return url_for("main.dashboard")
    parsed = urlparse(value)
    if parsed.netloc or parsed.scheme or not parsed.path.startswith("/"):
        return url_for("main.dashboard")
    return parsed.path


@auth.get("/login")
@limiter.limit("20 per hour")
def login():
    if current_user():
        return redirect(url_for("main.dashboard"))
    return render_template(
        "login.html",
        configuration_error=(
            None
            if settings.oauth_ready
            else "Discord OAuth2 ist in der .env noch nicht vollständig konfiguriert."
        ),
        next_url=_safe_next(request.args.get("next")),
    )


@auth.get("/login/discord")
@limiter.limit("20 per hour")
def discord_login():
    if current_user():
        return redirect(url_for("main.dashboard"))
    if not settings.oauth_ready:
        return redirect(url_for("auth.login"))
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["login_next"] = _safe_next(request.args.get("next"))
    parameters = urlencode(
        {
            "client_id": settings.discord_client_id,
            "redirect_uri": settings.discord_redirect_uri,
            "response_type": "code",
            "scope": "identify guilds.members.read",
            "state": state,
            "prompt": "none",
        }
    )
    return redirect(f"https://discord.com/oauth2/authorize?{parameters}")


@auth.get("/oauth/callback")
@limiter.limit("20 per hour")
def callback():
    expected_state = session.pop("oauth_state", None)
    supplied_state = request.args.get("state")
    if not expected_state or not secrets.compare_digest(
        expected_state, supplied_state or ""
    ):
        flash("Die Anmeldung ist abgelaufen. Bitte versuche es erneut.", "error")
        return redirect(url_for("auth.login"))
    if request.args.get("error"):
        flash("Die Discord-Anmeldung wurde abgebrochen.", "error")
        return redirect(url_for("auth.login"))
    code = request.args.get("code", "")
    try:
        token_response = requests.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
            },
            timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        user_response = requests.get(
            f"{DISCORD_API}/users/@me", headers=headers, timeout=10
        )
        member_response = requests.get(
            f"{DISCORD_API}/users/@me/guilds/{settings.guild_id}/member",
            headers=headers,
            timeout=10,
        )
        user_response.raise_for_status()
        if member_response.status_code == 404:
            flash("Du bist kein Mitglied des konfigurierten Discord-Servers.", "error")
            return redirect(url_for("auth.login"))
        member_response.raise_for_status()
    except (requests.RequestException, KeyError, ValueError):
        flash("Discord konnte die Anmeldung nicht abschließen.", "error")
        return redirect(url_for("auth.login"))

    user = user_response.json()
    member = member_response.json()
    avatar_hash = user.get("avatar")
    avatar = (
        f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar_hash}.png?size=128"
        if avatar_hash
        else f"https://cdn.discordapp.com/embed/avatars/{(int(user['id']) >> 22) % 6}.png"
    )
    destination = session.get("login_next")
    session.clear()
    session.permanent = True
    session["user"] = {
        "id": str(user["id"]),
        "username": user.get("global_name") or user["username"],
        "tag": user["username"],
        "avatar": avatar,
        "roles": [str(item) for item in member.get("roles", [])],
        "guild_permissions": str(member.get("permissions", "0")),
    }
    return redirect(_safe_next(destination))


@auth.post("/logout")
def logout():
    session.clear()
    flash("Du wurdest sicher abgemeldet.", "success")
    return redirect(url_for("auth.login"))
