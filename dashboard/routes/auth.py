"""Discord OAuth2 login with membership and state validation."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests
from flask import Blueprint, abort, flash, redirect, request, session, url_for

from bot import runtime
from config import settings

bp = Blueprint("auth", __name__)
DISCORD_API = "https://discord.com/api/v10"


@bp.get("/login")
def login():
    if not settings.oauth_ready:
        flash("Discord OAuth2 ist noch nicht vollständig in der .env eingerichtet.", "error")
        return redirect(url_for("main.index"))
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    query = urlencode(
        {
            "client_id": settings.discord_client_id,
            "redirect_uri": settings.discord_redirect_uri,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
            "prompt": "none",
        }
    )
    return redirect(f"https://discord.com/oauth2/authorize?{query}")


@bp.get("/callback")
def callback():
    expected = session.pop("oauth_state", None)
    if not expected or not secrets.compare_digest(
        str(expected), str(request.args.get("state", ""))
    ):
        abort(400, "Die OAuth2-State-Prüfung ist fehlgeschlagen.")
    code = request.args.get("code", "")
    if not code:
        flash("Die Discord-Anmeldung wurde abgebrochen.", "error")
        return redirect(url_for("main.index"))
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
        token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        user_response = requests.get(f"{DISCORD_API}/users/@me", headers=headers, timeout=10)
        guild_response = requests.get(
            f"{DISCORD_API}/users/@me/guilds", headers=headers, timeout=10
        )
        user_response.raise_for_status()
        guild_response.raise_for_status()
    except (requests.RequestException, KeyError, ValueError):
        flash("Discord konnte die Anmeldung nicht abschließen. Bitte versuche es erneut.", "error")
        return redirect(url_for("main.index"))
    user = user_response.json()
    guild_ids = {str(item["id"]) for item in guild_response.json()}
    if str(settings.guild_id) not in guild_ids:
        flash("Du bist kein Mitglied des konfigurierten Discord-Servers.", "error")
        return redirect(url_for("main.index"))
    try:
        snapshot = runtime.call("dashboard_snapshot", int(user["id"]), timeout=8)
    except (runtime.BotUnavailable, TimeoutError, ValueError):
        snapshot = None
    is_initial_admin = int(user["id"]) in settings.initial_admin_discord_ids
    if not is_initial_admin and (not snapshot or not snapshot.get("member")):
        flash("Deine Serverrollen konnten gerade nicht sicher geprüft werden.", "error")
        return redirect(url_for("main.index"))
    avatar_hash = user.get("avatar")
    avatar = (
        f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar_hash}.png?size=128"
        if avatar_hash
        else f"https://cdn.discordapp.com/embed/avatars/{int(user.get('discriminator', '0') or 0) % 5}.png"
    )
    session.clear()
    session["user"] = {
        "id": str(user["id"]),
        "username": user.get("global_name") or user["username"],
        "tag": user["username"],
        "avatar": avatar,
    }
    session.permanent = True
    flash("Willkommen zurück!", "success")
    return redirect(url_for("main.dashboard"))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.index"))
