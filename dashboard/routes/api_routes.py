"""JSON-API für Dashboard-Frontend (Rollen/Kanäle etc.)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from dashboard.api.bot_client import BotAPIError, list_channels, list_roles, post
from dashboard.auth import login_required, require_perms

bp = Blueprint("api", __name__)


@bp.route("/roles")
@login_required
def roles():
    if not require_perms("dashboard.access"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    force = request.args.get("force") == "1"
    try:
        data = list_roles(force=force)
        # Filter managed / above bot for selection unless include_all
        include_all = request.args.get("all") == "1"
        if not include_all:
            data = [r for r in data if r.get("selectable")]
        return jsonify({"ok": True, "data": data})
    except BotAPIError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503


@bp.route("/channels")
@login_required
def channels():
    if not require_perms("dashboard.access"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    force = request.args.get("force") == "1"
    channel_type = request.args.get("type", "all")
    try:
        data = list_channels(channel_type=channel_type, force=force)
        return jsonify({"ok": True, "data": data})
    except BotAPIError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503


@bp.route("/cache/refresh", methods=["POST"])
@login_required
def refresh_cache():
    if not require_perms("dashboard.access"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    try:
        post("/cache/invalidate", {})
        roles = list_roles(force=True)
        channels = list_channels(force=True)
        return jsonify({"ok": True, "roles": len(roles), "channels": len(channels)})
    except BotAPIError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
