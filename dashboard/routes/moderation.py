"""Moderations-Dashboard."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from bot.utils.audit import write_audit
from dashboard.api.bot_client import BotAPIError, post
from dashboard.auth import current_user, login_required, permission_required
from database.manager import get_session
from database.models import ModCase

bp = Blueprint("moderation", __name__)


@bp.route("/")
@login_required
@permission_required("moderation.use")
def index():
    q = request.args.get("q", "").strip()
    action = request.args.get("action", "")
    with get_session() as session:
        query = session.query(ModCase).order_by(ModCase.created_at.desc())
        if action:
            query = query.filter(ModCase.action == action)
        if q:
            if q.isdigit():
                query = query.filter(
                    (ModCase.user_id == int(q))
                    | (ModCase.case_number == int(q))
                    | (ModCase.user_name.ilike(f"%{q}%"))
                )
            else:
                query = query.filter(ModCase.user_name.ilike(f"%{q}%"))
        cases = query.limit(200).all()
        total = session.query(ModCase).count()
        warns = session.query(ModCase).filter(ModCase.action == "warn", ModCase.status == "active").count()
        bans = session.query(ModCase).filter(ModCase.action.in_(["ban", "tempban"]), ModCase.status == "active").count()
    return render_template(
        "dashboard/moderation/index.html",
        cases=cases,
        stats={"total": total, "warns": warns, "bans": bans},
    )


@bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required("moderation.use")
def create():
    if request.method == "POST":
        user = current_user()
        payload = {
            "action": request.form.get("action"),
            "user_id": int(request.form.get("user_id") or 0),
            "reason": request.form.get("reason") or "Kein Grund angegeben",
            "duration_seconds": int(request.form.get("duration_seconds") or 0),
            "moderator_id": int(user["id"]),
            "moderator_name": user["username"],
            "evidence": request.form.get("evidence") or "",
            "nickname": request.form.get("nickname") or "",
        }
        try:
            result = post("/moderation/action", payload)
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action=f"Moderation: {payload['action']}",
                area="moderation",
                after=payload,
                ip_address=request.remote_addr or "",
            )
            flash(f"Fall #{result.get('case_number')} erstellt.", "success")
            return redirect(url_for("moderation.index"))
        except BotAPIError as exc:
            flash(str(exc), "error")
    return render_template("dashboard/moderation/create.html")


@bp.route("/<int:case_id>/revoke", methods=["POST"])
@login_required
@permission_required("moderation.use")
def revoke(case_id: int):
    from datetime import datetime, timezone

    user = current_user()
    with get_session() as session:
        case = session.get(ModCase, case_id)
        if not case:
            flash("Fall nicht gefunden.", "error")
            return redirect(url_for("moderation.index"))
        case.status = "revoked"
        case.revoked_by = int(user["id"])
        case.revoked_at = datetime.now(timezone.utc)
        case.revoke_reason = request.form.get("reason") or "Aufgehoben"
        if case.action in {"ban", "tempban"}:
            try:
                post(
                    "/moderation/action",
                    {
                        "action": "unban",
                        "user_id": case.user_id,
                        "reason": case.revoke_reason,
                        "moderator_id": int(user["id"]),
                        "moderator_name": user["username"],
                    },
                )
            except BotAPIError as exc:
                flash(str(exc), "error")
        flash(f"Fall #{case.case_number} aufgehoben.", "success")
    return redirect(url_for("moderation.index"))
