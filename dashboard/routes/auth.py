"""Auth-Routen: Discord OAuth2 Login/Logout."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, request, session, url_for

import config
from bot.utils.permissions import is_initial_admin, user_permissions
from dashboard.auth import (
    avatar_url,
    exchange_code,
    fetch_guild_member,
    fetch_user,
    login_url,
)

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login():
    if not config.DISCORD_CLIENT_ID or not config.DISCORD_CLIENT_SECRET:
        flash("OAuth2 ist nicht konfiguriert. Bitte .env prüfen.", "error")
        return redirect(url_for("main.landing"))
    return redirect(login_url())


@bp.route("/auth/callback")
def callback():
    error = request.args.get("error")
    if error:
        flash(f"Discord-Login abgebrochen: {error}", "error")
        return redirect(url_for("main.landing"))

    state = request.args.get("state")
    if not state or state != session.get("oauth_state"):
        flash("Ungültiger OAuth-State. Bitte erneut anmelden.", "error")
        return redirect(url_for("main.landing"))

    code = request.args.get("code")
    if not code:
        flash("Kein Autorisierungscode erhalten.", "error")
        return redirect(url_for("main.landing"))

    try:
        token = exchange_code(code)
        access_token = token["access_token"]
        user = fetch_user(access_token)
        member = fetch_guild_member(access_token, config.GUILD_ID)
    except Exception as exc:
        flash(f"Login fehlgeschlagen: {exc}", "error")
        return redirect(url_for("main.landing"))

    user_id = int(user["id"])
    if not member and not is_initial_admin(user_id):
        flash("Du bist kein Mitglied des Servers.", "error")
        return redirect(url_for("main.landing"))

    role_ids = []
    if member:
        role_ids = [int(r) for r in member.get("roles", [])]

    perms = user_permissions(user_id, role_ids)
    if "dashboard.access" not in perms and "admin.full" not in perms and not is_initial_admin(user_id):
        flash("Du hast keine Berechtigung für das Dashboard.", "error")
        return redirect(url_for("main.landing"))

    session.clear()
    session.permanent = True
    session["user"] = {
        "id": str(user_id),
        "username": user.get("global_name") or user.get("username") or "User",
        "discriminator": user.get("discriminator") or "0",
        "avatar_url": avatar_url(user),
    }
    session["role_ids"] = role_ids
    session["access_token"] = access_token
    flash(f"Willkommen, {session['user']['username']}!", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/logout")
def logout():
    session.clear()
    flash("Abgemeldet.", "info")
    return redirect(url_for("main.landing"))
