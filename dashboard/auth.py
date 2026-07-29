"""Discord OAuth2 und Session-Hilfen."""

from __future__ import annotations

import secrets
from functools import wraps
from typing import Callable, Optional
from urllib.parse import urlencode

import requests
from flask import redirect, request, session, url_for, flash, abort

import config
from bot.utils.permissions import has_any, has_permission, user_permissions, is_initial_admin
from dashboard.api.bot_client import BotAPIError, get


def login_url() -> str:
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": config.OAUTH_SCOPES,
        "state": state,
        "prompt": "consent",
    }
    return f"{config.DISCORD_OAUTH_AUTHORIZE}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(config.DISCORD_OAUTH_TOKEN, data=data, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError("Token-Austausch fehlgeschlagen.")
    return resp.json()


def fetch_user(access_token: str) -> dict:
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError("Benutzerprofil konnte nicht geladen werden.")
    return resp.json()


def fetch_guild_member(access_token: str, guild_id: int) -> Optional[dict]:
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me/guilds/{guild_id}/member",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


def avatar_url(user: dict) -> str:
    user_id = user.get("id")
    avatar = user.get("avatar")
    if user_id and avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=128"
    discr = int(user.get("discriminator") or 0) % 5
    return f"https://cdn.discordapp.com/embed/avatars/{discr}.png"


def current_user() -> Optional[dict]:
    return session.get("user")


def current_role_ids() -> list[int]:
    return [int(r) for r in session.get("role_ids", [])]


def current_perms() -> set[str]:
    user = current_user()
    if not user:
        return set()
    return user_permissions(int(user["id"]), current_role_ids())


def login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def permission_required(*perms: str):
    def decorator(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("auth.login"))
            uid = int(user["id"])
            roles = current_role_ids()
            if is_initial_admin(uid):
                return view(*args, **kwargs)
            if not has_any(uid, roles, "dashboard.access", "admin.full"):
                flash("Kein Dashboard-Zugriff.", "error")
                abort(403)
            # Spezielle Seiten: eine der genannten Rechte ODER admin.full
            needed = perms or ("dashboard.access",)
            if not has_any(uid, roles, *needed, "admin.full"):
                flash("Keine Berechtigung für diesen Bereich.", "error")
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def require_perms(*perms: str) -> bool:
    user = current_user()
    if not user:
        return False
    if is_initial_admin(int(user["id"])):
        return True
    return has_any(int(user["id"]), current_role_ids(), *perms, "admin.full")
