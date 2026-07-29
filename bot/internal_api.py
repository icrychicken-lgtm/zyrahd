"""Authenticated loopback API used by the web dashboard."""

from __future__ import annotations

import asyncio
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable

import discord
from flask import Flask, jsonify, request
from sqlalchemy import select

from bot.cogs.tickets import TicketPanel
from bot.cogs.utility import VerifyView
from config import settings
from database.manager import session_scope
from database.models import Ticket, TicketMessage


def create_internal_app(bot: discord.Client) -> Flask:
    app = Flask("zyrahd-internal-api")
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

    @app.before_request
    def authenticate() -> tuple[Any, int] | None:
        if request.endpoint == "health":
            return None
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = settings.internal_api_secret
        if not expected or not hmac.compare_digest(supplied, expected):
            return jsonify(error="Interne API: Zugriff verweigert."), 401
        return None

    def guild() -> discord.Guild | None:
        return bot.get_guild(settings.guild_id)

    def run(coro: Awaitable[Any], timeout: float = 25) -> Any:
        loop = getattr(bot, "main_loop", None)
        if not loop or not loop.is_running():
            raise RuntimeError("Discord-Bot ist nicht verbunden.")
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)

    @app.get("/health")
    def health() -> tuple[Any, int]:
        current = guild()
        return (
            jsonify(
                online=bool(bot.is_ready()),
                bot=str(bot.user) if bot.user else None,
                guild=current.name if current else None,
                member_count=current.member_count if current else None,
                latency=round(bot.latency * 1000) if bot.is_ready() else None,
            ),
            200,
        )

    @app.get("/resources")
    def resources() -> tuple[Any, int]:
        current = guild()
        if not current:
            return jsonify(error="Der konfigurierte Server ist nicht erreichbar."), 503
        top_role = current.me.top_role
        roles = [
            {
                "id": str(role.id),
                "name": role.name,
                "color": str(role.color),
                "position": role.position,
                "usable": not role.managed and role < top_role and not role.is_default(),
            }
            for role in reversed(current.roles)
            if not role.is_default()
        ]
        channels = [
            {
                "id": str(channel.id),
                "name": channel.name,
                "type": (
                    "category"
                    if isinstance(channel, discord.CategoryChannel)
                    else "voice"
                    if isinstance(channel, discord.VoiceChannel)
                    else "forum"
                    if isinstance(channel, discord.ForumChannel)
                    else "announcement"
                    if isinstance(channel, discord.TextChannel) and channel.is_news()
                    else "text"
                ),
            }
            for channel in current.channels
        ]
        return (
            jsonify(
                guild={
                    "id": str(current.id),
                    "name": current.name,
                    "icon": current.icon.url if current.icon else None,
                    "member_count": current.member_count,
                },
                roles=roles,
                channels=channels,
                members=[
                    {
                        "id": str(member.id),
                        "name": member.display_name,
                        "subtitle": str(member),
                        "avatar": member.display_avatar.url,
                    }
                    for member in current.members
                    if not member.bot
                ],
            ),
            200,
        )

    @app.post("/tickets")
    def create_ticket() -> tuple[Any, int]:
        data = request.get_json(silent=True) or {}
        user_id = str(data.get("user_id", ""))
        if not user_id.isdigit() or not str(data.get("ticket_type_id", "")).isdigit():
            return jsonify(error="Ungültige Ticket-Anfrage."), 400
        current = guild()
        member = current.get_member(int(user_id)) if current else None
        if not member:
            return jsonify(error="Du bist kein Mitglied des Servers."), 403
        cog = bot.get_cog("TicketCog")
        if not cog:
            return jsonify(error="Ticket-Modul ist nicht geladen."), 503
        try:
            ticket = run(
                cog.create_ticket(
                    member,
                    int(data["ticket_type_id"]),
                    {
                        str(key): str(value)[:4000]
                        for key, value in (data.get("form_data") or {}).items()
                    },
                )
            )
        except (RuntimeError, ValueError, TimeoutError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(id=ticket.id, number=ticket.number, channel_id=ticket.channel_id), 201

    @app.post("/tickets/<int:ticket_id>/messages")
    def send_ticket_message(ticket_id: int) -> tuple[Any, int]:
        data = request.get_json(silent=True) or {}
        content = str(data.get("content", "")).strip()
        if not content or len(content) > 2000:
            return jsonify(error="Die Nachricht muss 1 bis 2000 Zeichen haben."), 400
        with session_scope() as session:
            ticket = session.get(Ticket, ticket_id)
            if not ticket or not ticket.channel_id or ticket.status == "closed":
                return jsonify(error="Das Ticket ist nicht beschreibbar."), 404
            channel_id = int(ticket.channel_id)

        async def send() -> discord.Message:
            channel = bot.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise ValueError("Der Discord-Kanal wurde nicht gefunden.")
            embed = discord.Embed(
                description=content,
                color=0x8B5CF6,
                timestamp=datetime.now(UTC),
            )
            embed.set_author(name=f"{str(data.get('author_name', 'Dashboard'))} · Web")
            return await channel.send(embed=embed)

        try:
            message = run(send())
        except (RuntimeError, ValueError, TimeoutError) as exc:
            return jsonify(error=str(exc)), 503
        with session_scope() as session:
            session.add(
                TicketMessage(
                    ticket_id=ticket_id,
                    author_id=str(data.get("author_id", "")),
                    author_name=str(data.get("author_name", "Dashboard"))[:100],
                    author_avatar=str(data.get("author_avatar", "")) or None,
                    content=content,
                    source="web",
                    message_id=str(message.id),
                )
            )
        return jsonify(ok=True, message_id=str(message.id)), 201

    @app.post("/publish/<panel>")
    def publish_panel(panel: str) -> tuple[Any, int]:
        data = request.get_json(silent=True) or {}
        channel_id = str(data.get("channel_id", ""))
        current = guild()
        channel = current.get_channel(int(channel_id)) if current and channel_id.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            return jsonify(error="Bitte wähle einen gültigen Textkanal."), 400
        if panel == "ticket":
            embed = discord.Embed(
                title=str(data.get("title", "Support-Center"))[:256],
                description=str(
                    data.get(
                        "description",
                        "Benötigst du Hilfe? Erstelle hier ein privates Ticket.",
                    )
                )[:4096],
                color=0x8B5CF6,
            )
            view: discord.ui.View = TicketPanel()
        elif panel == "verify":
            embed = discord.Embed(
                title=str(data.get("title", "Verifizierung"))[:256],
                description=str(
                    data.get(
                        "description",
                        "Klicke auf den Button, um Zugriff auf den Server zu erhalten.",
                    )
                )[:4096],
                color=0x8B5CF6,
            )
            view = VerifyView()
        else:
            return jsonify(error="Unbekannter Panel-Typ."), 404
        try:
            message = run(channel.send(embed=embed, view=view))
        except (discord.HTTPException, RuntimeError, TimeoutError) as exc:
            return jsonify(error=f"Panel konnte nicht veröffentlicht werden: {exc}"), 503
        return jsonify(ok=True, message_id=str(message.id)), 201

    @app.post("/embeds")
    def send_embed() -> tuple[Any, int]:
        data = request.get_json(silent=True) or {}
        channel_id = str(data.get("channel_id", ""))
        current = guild()
        channel = current.get_channel(int(channel_id)) if current and channel_id.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            return jsonify(error="Bitte wähle einen Textkanal."), 400
        try:
            color = discord.Color.from_str(str(data.get("color", "#8b5cf6")))
        except ValueError:
            return jsonify(error="Ungültige Embed-Farbe."), 400
        embed = discord.Embed(
            title=str(data.get("title", ""))[:256] or None,
            description=str(data.get("description", ""))[:4096] or None,
            color=color,
            timestamp=datetime.now(UTC) if data.get("timestamp") else None,
        )
        footer = str(data.get("footer", ""))[:2048]
        if footer:
            embed.set_footer(text=footer)
        image = str(data.get("image", ""))
        thumbnail = str(data.get("thumbnail", ""))
        if image.startswith(("https://", "http://")):
            embed.set_image(url=image)
        if thumbnail.startswith(("https://", "http://")):
            embed.set_thumbnail(url=thumbnail)
        for field in (data.get("fields") or [])[:25]:
            if field.get("name") and field.get("value"):
                embed.add_field(
                    name=str(field["name"])[:256],
                    value=str(field["value"])[:1024],
                    inline=bool(field.get("inline")),
                )
        try:
            message = run(
                channel.send(
                    content=str(data.get("content", ""))[:2000] or None, embed=embed
                )
            )
        except (discord.HTTPException, RuntimeError, TimeoutError) as exc:
            return jsonify(error=f"Embed konnte nicht gesendet werden: {exc}"), 503
        return jsonify(ok=True, message_id=str(message.id)), 201

    @app.post("/moderate")
    def moderate() -> tuple[Any, int]:
        data = request.get_json(silent=True) or {}
        current = guild()
        user_id = str(data.get("user_id", ""))
        member = current.get_member(int(user_id)) if current and user_id.isdigit() else None
        if not member:
            return jsonify(error="Mitglied wurde nicht gefunden."), 404
        action = str(data.get("action", ""))
        reason = str(data.get("reason", "Über Dashboard"))[:512]

        async def perform() -> None:
            if action == "timeout":
                await member.timeout(
                    timedelta(minutes=max(1, min(int(data.get("minutes", 10)), 40320))),
                    reason=reason,
                )
            elif action == "kick":
                await member.kick(reason=reason)
            elif action == "ban":
                await member.ban(reason=reason)
            else:
                raise ValueError("Diese Moderationsaktion wird nicht unterstützt.")

        try:
            run(perform())
        except (discord.HTTPException, RuntimeError, ValueError, TimeoutError) as exc:
            return jsonify(error=f"Moderation fehlgeschlagen: {exc}"), 400
        return jsonify(ok=True), 200

    return app
