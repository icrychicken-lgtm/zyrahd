"""Embed- und Regel-Designer."""

from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from bot.utils.audit import write_audit
from dashboard.api.bot_client import BotAPIError, post
from dashboard.auth import current_user, login_required, permission_required
from database.manager import get_session
from database.models import EmbedMessage

bp = Blueprint("embeds", __name__)


@bp.route("/")
@login_required
@permission_required("messages.send")
def index():
    with get_session() as session:
        embeds = session.query(EmbedMessage).order_by(EmbedMessage.updated_at.desc()).all()
    return render_template("dashboard/embeds/index.html", embeds=embeds)


@bp.route("/editor", methods=["GET", "POST"])
@bp.route("/editor/<int:embed_id>", methods=["GET", "POST"])
@login_required
@permission_required("messages.send")
def editor(embed_id: int | None = None):
    with get_session() as session:
        emb = session.get(EmbedMessage, embed_id) if embed_id else None
        if request.method == "POST":
            if not emb:
                emb = EmbedMessage(name=request.form.get("name") or "Neues Embed")
                session.add(emb)
            emb.name = request.form.get("name") or emb.name
            emb.category = request.form.get("category") or "general"
            emb.content = request.form.get("content") or ""
            ch = request.form.get("channel_id") or ""
            emb.channel_id = int(ch) if ch.isdigit() else None

            fields = []
            names = request.form.getlist("field_name")
            values = request.form.getlist("field_value")
            inlines = request.form.getlist("field_inline")
            for i, (n, v) in enumerate(zip(names, values)):
                if not n and not v:
                    continue
                fields.append(
                    {
                        "name": n or "\u200b",
                        "value": v or "\u200b",
                        "inline": str(i) in inlines or (len(inlines) > i and inlines[i] == "on"),
                    }
                )

            embed_data = {
                "title": request.form.get("embed_title") or "",
                "description": request.form.get("embed_description") or "",
                "color": request.form.get("embed_color") or "#9B5CFF",
                "url": request.form.get("embed_url") or "",
                "thumbnail": request.form.get("embed_thumbnail") or "",
                "image": request.form.get("embed_image") or "",
                "timestamp": request.form.get("embed_timestamp") == "on",
                "author": {
                    "name": request.form.get("author_name") or "",
                    "icon_url": request.form.get("author_icon") or "",
                    "url": request.form.get("author_url") or "",
                },
                "footer": {
                    "text": request.form.get("footer_text") or "",
                    "icon_url": request.form.get("footer_icon") or "",
                },
                "fields": fields,
            }
            emb.embed_json = json.dumps(embed_data, ensure_ascii=False)

            buttons = []
            blabels = request.form.getlist("btn_label")
            burls = request.form.getlist("btn_url")
            for label, url in zip(blabels, burls):
                if label and url:
                    buttons.append({"label": label, "url": url})
            emb.buttons_json = json.dumps(buttons, ensure_ascii=False)

            publish = request.form.get("publish") == "1"
            session.flush()
            eid = emb.id

            if publish and emb.channel_id:
                try:
                    payload = {
                        "channel_id": emb.channel_id,
                        "content": emb.content or None,
                        "embed": embed_data,
                    }
                    if emb.message_id:
                        payload["message_id"] = emb.message_id
                        result = post("/embeds/edit", payload)
                    else:
                        result = post("/embeds/send", payload)
                    emb.message_id = int(result["message_id"])
                    emb.published = True
                    flash("Nachricht veröffentlicht.", "success")
                except BotAPIError as exc:
                    flash(str(exc), "error")
            else:
                flash("Embed gespeichert.", "success")

            user = current_user()
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action=f"Embed gespeichert: {emb.name}",
                area="embeds",
                ip_address=request.remote_addr or "",
            )
            return redirect(url_for("embeds.editor", embed_id=eid))

        embed_data = emb.get_embed() if emb else {}
        buttons = emb.get_buttons() if emb else []
    return render_template(
        "dashboard/embeds/editor.html",
        emb=emb,
        embed_data=embed_data,
        buttons=buttons,
    )


@bp.route("/<int:embed_id>/delete", methods=["POST"])
@login_required
@permission_required("messages.send")
def delete(embed_id: int):
    with get_session() as session:
        emb = session.get(EmbedMessage, embed_id)
        if emb:
            session.delete(emb)
            flash("Embed gelöscht.", "success")
    return redirect(url_for("embeds.index"))
