"""Discord ticket channel creation and synchronization helpers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from sqlalchemy import func, select

from database.manager import session_scope
from database.models import Ticket, TicketMessage, TicketType


def _safe_channel_name(value: str) -> str:
    value = value.lower().replace(" ", "-")
    value = re.sub(r"[^a-z0-9äöüß_-]", "", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return (value or "ticket")[:95]


def _validate_answers(
    fields: list[dict[str, Any]], answers: dict[str, Any]
) -> dict[str, str]:
    clean: dict[str, str] = {}
    for field in fields:
        key = str(field.get("id", "")).strip()
        if not key:
            continue
        value = str(answers.get(key, "")).strip()
        if field.get("required") and not value:
            raise ValueError(f"„{field.get('label', key)}“ ist ein Pflichtfeld.")
        minimum = max(0, int(field.get("min_length", 0) or 0))
        maximum = min(4000, int(field.get("max_length", 1000) or 1000))
        if value and len(value) < minimum:
            raise ValueError(f"„{field.get('label', key)}“ ist zu kurz.")
        if len(value) > maximum:
            raise ValueError(f"„{field.get('label', key)}“ ist zu lang.")
        if value:
            clean[key] = value
    return clean


async def create_ticket(
    bot: discord.Client,
    *,
    guild_id: int,
    ticket_type_id: int,
    creator_id: int,
    creator_name: str,
    answers: dict[str, Any],
) -> dict[str, Any]:
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise ValueError("Der konfigurierte Discord-Server ist nicht erreichbar.")
    member = guild.get_member(creator_id)
    if member is None:
        try:
            member = await guild.fetch_member(creator_id)
        except discord.NotFound as exc:
            raise PermissionError("Du bist kein Mitglied dieses Discord-Servers.") from exc

    now = datetime.now(timezone.utc)
    with session_scope() as db:
        kind = db.get(TicketType, ticket_type_id)
        if kind is None or kind.guild_id != str(guild_id) or not kind.enabled:
            raise ValueError("Diese Ticket-Art ist nicht verfügbar.")
        clean_answers = _validate_answers(kind.form_fields, answers)
        open_count = db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.guild_id == str(guild_id),
                Ticket.ticket_type_id == kind.id,
                Ticket.creator_id == str(creator_id),
                Ticket.status.in_(("open", "claimed", "waiting")),
            )
        )
        if int(open_count or 0) >= max(1, kind.max_open):
            raise ValueError("Du hast bereits die maximal erlaubte Anzahl offener Tickets.")
        latest = db.scalar(
            select(Ticket)
            .where(
                Ticket.guild_id == str(guild_id),
                Ticket.creator_id == str(creator_id),
                Ticket.ticket_type_id == kind.id,
            )
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )
        if latest and latest.created_at:
            created = latest.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            retry_at = created + timedelta(minutes=max(0, kind.cooldown_minutes))
            if retry_at > now and latest.status not in ("open", "claimed", "waiting"):
                seconds = int((retry_at - now).total_seconds())
                raise ValueError(f"Bitte warte noch {max(1, seconds // 60 + 1)} Minuten.")
        draft = Ticket(
            guild_id=str(guild_id),
            ticket_type_id=kind.id,
            creator_id=str(creator_id),
            creator_name=creator_name[:100],
            status="open",
            priority=kind.priority,
            subject=kind.name,
        )
        draft.form_data = clean_answers
        db.add(draft)
        db.flush()
        ticket_id = draft.id
        kind_data = {
            "name": kind.name,
            "color": kind.color,
            "category_id": kind.category_id,
            "support_roles": kind.support_role_ids,
            "welcome": kind.welcome_message,
            "ping_roles": kind.ping_roles,
            "format": kind.channel_format,
            "fields": kind.form_fields,
        }

    try:
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
        }
        me = guild.me
        if me:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True,
            )
        mention_roles: list[discord.Role] = []
        for role_id in kind_data["support_roles"]:
            role = guild.get_role(int(role_id))
            if role and not role.managed:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )
                mention_roles.append(role)
        category = None
        if kind_data["category_id"]:
            candidate = guild.get_channel(int(kind_data["category_id"]))
            if isinstance(candidate, discord.CategoryChannel):
                category = candidate
        format_values = {
            "number": ticket_id,
            "user": member.display_name,
            "type": kind_data["name"],
        }
        try:
            raw_name = kind_data["format"].format_map(format_values)
        except (KeyError, ValueError):
            raw_name = f"ticket-{ticket_id}-{member.display_name}"
        channel = await guild.create_text_channel(
            _safe_channel_name(raw_name),
            category=category,
            overwrites=overwrites,
            topic=f"zyrahd Ticket #{ticket_id} · Ersteller {creator_id}",
            reason=f"Ticket #{ticket_id} über zyrahd.net",
        )
        color = int(str(kind_data["color"]).lstrip("#"), 16)
        embed = discord.Embed(
            title=f"{kind_data['name']} · Ticket #{ticket_id}",
            description=kind_data["welcome"],
            color=color,
            timestamp=now,
        )
        embed.set_author(name=creator_name, icon_url=member.display_avatar.url)
        fields_by_id = {str(f.get("id")): f for f in kind_data["fields"]}
        for key, value in clean_answers.items():
            label = fields_by_id.get(key, {}).get("label", key)
            embed.add_field(name=str(label)[:256], value=value[:1024], inline=False)
        mentions = " ".join(role.mention for role in mention_roles)
        message = await channel.send(
            content=mentions if kind_data["ping_roles"] and mentions else None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        from bot.views.ticket_actions import TicketActionsView

        await message.edit(view=TicketActionsView(ticket_id))
    except Exception:
        with session_scope() as db:
            failed = db.get(Ticket, ticket_id)
            if failed:
                db.delete(failed)
        raise

    with session_scope() as db:
        saved = db.get(Ticket, ticket_id)
        if saved:
            saved.discord_channel_id = str(channel.id)
            saved.updated_at = now
    return {
        "id": ticket_id,
        "channel_id": str(channel.id),
        "channel_name": channel.name,
        "status": "open",
    }


async def send_web_message(
    bot: discord.Client,
    ticket_id: int,
    author_id: int,
    author_name: str,
    content: str,
) -> dict[str, Any]:
    content = content.strip()
    if not content or len(content) > 2000:
        raise ValueError("Die Nachricht muss zwischen 1 und 2.000 Zeichen lang sein.")
    with session_scope() as db:
        ticket = db.get(Ticket, ticket_id)
        if not ticket or not ticket.discord_channel_id:
            raise ValueError("Der Ticket-Kanal ist nicht verfügbar.")
        channel_id = int(ticket.discord_channel_id)
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Der Ticket-Kanal wurde gelöscht oder ist nicht erreichbar.")
    embed = discord.Embed(description=content, color=0x7C5CFF)
    embed.set_author(name=f"{author_name} · Web-Dashboard")
    sent = await channel.send(embed=embed)
    with session_scope() as db:
        row = TicketMessage(
            ticket_id=ticket_id,
            author_id=str(author_id),
            author_name=author_name[:100],
            content=content,
            source="web",
            discord_message_id=str(sent.id),
        )
        db.add(row)
        db.flush()
        message_id = row.id
    return {"id": message_id, "discord_message_id": str(sent.id)}
