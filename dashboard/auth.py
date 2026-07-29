"""Discord OAuth2 login and session lifecycle."""

from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import requests
from flask import Blueprint, flash, redirect, request, session, url_for

from config import settings

auth_bp = Blueprint("auth", __name__)
DISCORD_API = "https://discord.com/api/v10"
DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"


@auth_bp.get("/login")
def login():
    if not all(
        (
            settings.discord_client_id,
            settings.discord_client_secret,
            settings.discord_redirect_uri,
            settings.guild_id,
        )
    ):
        flash("Discord OAuth2 ist noch nicht vollständig konfiguriert.", "error")
        return redirect(url_for("pages.index"))

    state = secrets.token_urlsafe(32)
    session.clear()
    session["oauth_state"] = state
    query = urlencode(
        {
            "client_id": settings.discord_client_id,
            "redirect_uri": settings.discord_redirect_uri,
            "response_type": "code",
            "scope": "identify guilds.members.read",
            "state": state,
            "prompt": "none",
        }
    )
    return redirect(f"{DISCORD_AUTHORIZE}?{query}")


@auth_bp.get("/callback")
def callback():
    expected_state = session.pop("oauth_state", "")
    received_state = request.args.get("state", "")
    code = request.args.get("code", "")
    if not expected_state or not secrets.compare_digest(expected_state, received_state):
        flash("Die Anmeldung ist abgelaufen. Bitte versuche es erneut.", "error")
        return redirect(url_for("pages.index"))
    if not code:
        flash("Discord hat die Anmeldung abgebrochen.", "error")
        return redirect(url_for("pages.index"))

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
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        user_response = requests.get(
            f"{DISCORD_API}/users/@me", headers=headers, timeout=10
        )
        user_response.raise_for_status()
        member_response = requests.get(
            f"{DISCORD_API}/users/@me/guilds/{settings.guild_id}/member",
            headers=headers,
            timeout=10,
        )
        if member_response.status_code == 404:
            flash("Du bist kein Mitglied des konfigurierten Discord-Servers.", "error")
            return redirect(url_for("pages.index"))
        member_response.raise_for_status()
    except (requests.RequestException, KeyError, ValueError):
        flash("Discord konnte die Anmeldung nicht bestätigen.", "error")
        return redirect(url_for("pages.index"))

    user = user_response.json()
    member = member_response.json()
    avatar_hash = user.get("avatar")
    user["avatar_url"] = (
        f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar_hash}.png?size=128"
        if avatar_hash
        else "https://cdn.discordapp.com/embed/avatars/0.png"
    )
    session.clear()
    session.permanent = True
    session["discord_user"] = user
    session["discord_roles"] = member.get("roles", [])
    session["roles_checked_at"] = time.time()
    session["discord_member"] = {
        "nick": member.get("nick"),
        "joined_at": member.get("joined_at"),
    }
    flash(f"Willkommen, {user.get('global_name') or user['username']}!", "success")
    return redirect(url_for("pages.dashboard"))


@auth_bp.post("/logout")
def logout():
    session.clear()
    flash("Du wurdest sicher abgemeldet.", "success")
    return redirect(url_for("pages.index"))


def refresh_member_session(max_age_seconds: int = 60) -> bool:
    """Refresh guild membership and roles used for authorization.

    Discord outages do not invalidate an otherwise valid session, but a
    confirmed 404 immediately revokes dashboard access.
    """
    user = session.get("discord_user")
    if not user:
        return True
    last_check = float(session.get("roles_checked_at", 0))
    if time.time() - last_check < max_age_seconds:
        return True
    try:
        response = requests.get(
            f"{DISCORD_API}/guilds/{settings.guild_id}/members/{user['id']}",
            headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            timeout=8,
        )
    except requests.RequestException:
        return True
    if response.status_code == 404:
        session.clear()
        return False
    if not response.ok:
        return True
    try:
        member = response.json()
        session["discord_roles"] = member.get("roles", [])
        session["discord_member"] = {
            "nick": member.get("nick"),
            "joined_at": member.get("joined_at"),
        }
        session["roles_checked_at"] = time.time()
    except (TypeError, ValueError):
        return True
    return True
