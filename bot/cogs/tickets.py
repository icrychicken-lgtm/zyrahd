"""Ticket-System Cog und Hilfsfunktionen."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import config
from bot.utils.audit import write_activity
from bot.utils.helpers import parse_color
from bot.views.tickets import TicketControlView
from database.manager import get_session
from database.models import Ticket, TicketMessage, TicketPanel, TicketType, _json_dumps

logger = logging.getLogger("zyrahd.tickets")


async def create_ticket_channel(bot: commands.Bot, data: dict) -> dict:
    ticket_type_id = int(data["ticket_type_id"])
    opener_id = int(data["opener_id"])
    opener_name = data.get("opener_name") or str(opener_id)
    form_data = data.get("form_data") or {}

    guild = bot.get_guild(config.GUILD_ID)
    if not guild:
        raise ValueError("Server nicht gefunden.")

    with get_session() as session:
        tt = session.get(TicketType, ticket_type_id)
        if not tt or not tt.enabled:
            raise ValueError("Ticket-Art nicht verfügbar.")

        open_count = (
            session.query(Ticket)
            .filter(
                Ticket.opener_id == opener_id,
                Ticket.ticket_type_id == ticket_type_id,
                Ticket.status.in_(["open", "claimed", "waiting"]),
            )
            .count()
        )
        if open_count >= tt.max_open_per_user:
            raise ValueError(
                f"Du hast bereits die maximale Anzahl offener Tickets ({tt.max_open_per_user})."
            )

        if tt.cooldown_seconds > 0:
            last = (
                session.query(Ticket)
                .filter(Ticket.opener_id == opener_id, Ticket.ticket_type_id == ticket_type_id)
                .order_by(Ticket.created_at.desc())
                .first()
            )
            if last and last.created_at:
                created = last.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - created).total_seconds()
                if elapsed < tt.cooldown_seconds:
                    remaining = int(tt.cooldown_seconds - elapsed)
                    raise ValueError(f"Bitte warte noch {remaining} Sekunden.")

        # Öffnungszeiten (optional JSON: {"enabled": true, "start": "09:00", "end": "22:00"})
        hours = {}
        try:
            hours = json.loads(tt.open_hours_json or "{}")
        except json.JSONDecodeError:
            hours = {}
        if hours.get("enabled"):
            from bot.utils.helpers import tz_now

            now = tz_now()
            start = hours.get("start", "00:00")
            end = hours.get("end", "23:59")
            try:
                sh, sm = map(int, start.split(":"))
                eh, em = map(int, end.split(":"))
                start_m = sh * 60 + sm
                end_m = eh * 60 + em
                cur = now.hour * 60 + now.minute
                if not (start_m <= cur <= end_m):
                    raise ValueError(f"Tickets sind nur von {start} bis {end} Uhr möglich.")
            except ValueError:
                raise
            except Exception:
                pass

        last_ticket = session.query(Ticket).order_by(Ticket.ticket_number.desc()).first()
        ticket_number = (last_ticket.ticket_number + 1) if last_ticket else 1

        category_id = tt.category_id
        staff_roles = tt.get_staff_roles()
        greeting = tt.greeting_message
        ping_staff = tt.ping_staff
        color = tt.color
        priority = tt.priority
        name_format = tt.name_format
        type_name = tt.name
        type_emoji = tt.emoji
        log_channel_id = tt.log_channel_id

        member = guild.get_member(opener_id)
        username = member.name if member else opener_name.split("#")[0]
        channel_name = (
            name_format.replace("{username}", username.lower()[:16])
            .replace("{id}", str(ticket_number))
            .replace("{type}", type_name.lower()[:12])
        )
        channel_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in channel_name)[:90]

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, manage_messages=True
            ),
        }
        if member:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True, read_message_history=True
            )
        for rid in staff_roles:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, attach_files=True, read_message_history=True
                )

        category = guild.get_channel(category_id) if category_id else None
        if category and not isinstance(category, discord.CategoryChannel):
            category = None

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                topic=f"Ticket #{ticket_number} • {type_name} • {opener_name}",
                reason=f"Ticket von {opener_name}",
            )
        except discord.HTTPException as exc:
            raise ValueError(f"Kanal konnte nicht erstellt werden: {exc}") from exc

        ticket = Ticket(
            ticket_number=ticket_number,
            ticket_type_id=ticket_type_id,
            opener_id=opener_id,
            opener_name=opener_name,
            channel_id=channel.id,
            status="open",
            priority=priority,
            title=f"{type_emoji} {type_name} #{ticket_number}",
            form_data=_json_dumps(form_data),
            last_activity_at=datetime.now(timezone.utc),
        )
        session.add(ticket)
        session.flush()
        ticket_id = ticket.id
        ticket_number = ticket.ticket_number

    # Embed im Ticket
    embed = discord.Embed(
        title=f"{type_emoji} {type_name} #{ticket_number}",
        description=greeting.replace("{mention}", f"<@{opener_id}>").replace("{username}", username),
        color=parse_color(color),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Ersteller", value=f"<@{opener_id}>", inline=True)
    embed.add_field(name="Priorität", value=priority, inline=True)
    for key, value in form_data.items():
        embed.add_field(name=str(key)[:256], value=str(value)[:1024] or "—", inline=False)
    embed.set_footer(text="zyrahd.net • Ticket-System")

    content = None
    if ping_staff and staff_roles:
        content = " ".join(f"<@&{rid}>" for rid in staff_roles)

    view = TicketControlView(ticket_id)
    # Persistente Custom-IDs – View ohne ticket_id Binding neu registrieren nicht nötig,
    # Action löst über Channel auf.
    try:
        msg = await channel.send(content=content, embed=embed, view=view)
        await channel.send(
            "Nutze die Buttons oder das Dashboard, um dieses Ticket zu verwalten."
        )
    except discord.HTTPException:
        msg = None

    with get_session() as session:
        session.add(
            TicketMessage(
                ticket_id=ticket_id,
                author_id=opener_id,
                author_name=opener_name,
                content="Ticket erstellt",
                source="system",
                is_system=True,
                discord_message_id=msg.id if msg else None,
            )
        )

    if log_channel_id:
        log_ch = guild.get_channel(log_channel_id)
        if isinstance(log_ch, discord.TextChannel):
            log_embed = discord.Embed(
                title="Neues Ticket",
                description=f"#{ticket_number} • {type_name}\nKanal: {channel.mention}",
                color=parse_color(color),
            )
            await log_ch.send(embed=log_embed)

    write_activity("ticket", f"Ticket #{ticket_number} erstellt von {opener_name}")
    return {
        "ticket_id": ticket_id,
        "ticket_number": ticket_number,
        "channel_id": str(channel.id),
    }


async def perform_ticket_action(bot: commands.Bot, data: dict) -> dict:
    ticket_id = int(data["ticket_id"])
    action = data["action"]
    actor_id = int(data.get("actor_id") or 0)
    actor_name = data.get("actor_name") or str(actor_id)
    reason = data.get("reason") or ""
    target_user_id = data.get("target_user_id")
    new_priority = data.get("priority")
    new_type_id = data.get("ticket_type_id")
    note = data.get("note") or ""

    guild = bot.get_guild(config.GUILD_ID)
    if not guild:
        raise ValueError("Server nicht gefunden.")

    with get_session() as session:
        ticket = session.get(Ticket, ticket_id)
        if not ticket:
            raise ValueError("Ticket nicht gefunden.")
        channel_id = ticket.channel_id
        opener_id = ticket.opener_id
        status = ticket.status
        ticket_number = ticket.ticket_number

        channel = guild.get_channel(channel_id) if channel_id else None

        if action == "claim":
            ticket.claimed_by = actor_id
            ticket.claimed_by_name = actor_name
            ticket.status = "claimed"
            message = f"Ticket von {actor_name} übernommen."
        elif action == "unclaim":
            ticket.claimed_by = None
            ticket.claimed_by_name = ""
            ticket.status = "open"
            message = "Übernahme aufgehoben."
        elif action == "close":
            ticket.status = "closed"
            ticket.close_reason = reason
            ticket.closed_by = actor_id
            ticket.closed_at = datetime.now(timezone.utc)
            message = f"Ticket geschlossen. Grund: {reason or '—'}"
        elif action == "reopen":
            ticket.status = "open"
            ticket.closed_by = None
            ticket.closed_at = None
            ticket.close_reason = ""
            message = "Ticket wieder geöffnet."
        elif action == "delete":
            ticket.status = "archived"
            message = "Ticket archiviert/gelöscht."
        elif action == "priority":
            ticket.priority = new_priority or ticket.priority
            message = f"Priorität auf {ticket.priority} gesetzt."
        elif action == "transfer":
            if new_type_id:
                ticket.ticket_type_id = int(new_type_id)
            message = "Ticket weitergeleitet."
        elif action == "add_user":
            users = ticket.get_added_users()
            uid = int(target_user_id)
            if uid not in users:
                users.append(uid)
            ticket.added_users = _json_dumps(users)
            if isinstance(channel, discord.TextChannel):
                member = guild.get_member(uid)
                if member:
                    await channel.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    )
            message = f"Benutzer <@{uid}> hinzugefügt."
        elif action == "remove_user":
            users = [u for u in ticket.get_added_users() if u != int(target_user_id)]
            ticket.added_users = _json_dumps(users)
            if isinstance(channel, discord.TextChannel):
                member = guild.get_member(int(target_user_id))
                if member:
                    await channel.set_permissions(member, overwrite=None)
            message = f"Benutzer <@{target_user_id}> entfernt."
        elif action == "note":
            ticket.internal_notes = (ticket.internal_notes + "\n" if ticket.internal_notes else "") + f"[{actor_name}] {note}"
            message = "Interne Notiz gespeichert."
        elif action == "title":
            ticket.title = data.get("title") or ticket.title
            message = f"Titel geändert zu: {ticket.title}"
        elif action == "rate":
            ticket.rating = int(data.get("rating") or 0)
            ticket.rating_comment = data.get("rating_comment") or ""
            message = "Bewertung gespeichert."
        else:
            raise ValueError(f"Unbekannte Aktion: {action}")

        ticket.last_activity_at = datetime.now(timezone.utc)
        session.add(
            TicketMessage(
                ticket_id=ticket.id,
                author_id=actor_id,
                author_name=actor_name,
                content=message,
                source="system",
                is_system=True,
            )
        )

    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(f"⚙️ {message}")
        except discord.HTTPException:
            pass

        if action == "close":
            # Channel umbenennen / sperren
            try:
                await channel.set_permissions(guild.default_role, view_channel=False)
                member = guild.get_member(opener_id)
                if member:
                    await channel.set_permissions(member, send_messages=False, view_channel=True)
                await channel.edit(name=f"closed-{channel.name}"[:90])
            except discord.HTTPException:
                pass
            # DM
            member = guild.get_member(opener_id)
            if member:
                try:
                    await member.send(
                        f"Dein Ticket #{ticket_number} wurde geschlossen.\nGrund: {reason or '—'}"
                    )
                except discord.HTTPException:
                    pass
        elif action == "delete":
            try:
                await channel.delete(reason=f"Ticket gelöscht von {actor_name}")
            except discord.HTTPException:
                pass
            with get_session() as session:
                ticket = session.get(Ticket, ticket_id)
                if ticket:
                    ticket.channel_id = None

    write_activity("ticket", f"Ticket #{ticket_number}: {message}")
    return {"message": message, "status": action}


class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if message.guild.id != config.GUILD_ID:
            return

        with get_session() as session:
            ticket = (
                session.query(Ticket)
                .filter(Ticket.channel_id == message.channel.id)
                .filter(Ticket.status.in_(["open", "claimed", "waiting"]))
                .first()
            )
            if not ticket:
                return
            attachments = [
                {"url": a.url, "filename": a.filename, "content_type": a.content_type}
                for a in message.attachments
            ]
            session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=message.author.id,
                    author_name=str(message.author),
                    author_avatar=str(message.author.display_avatar.url),
                    content=message.content or "",
                    attachments_json=_json_dumps(attachments),
                    source="discord",
                    discord_message_id=message.id,
                )
            )
            ticket.last_activity_at = datetime.now(timezone.utc)
            if ticket.status == "open" and message.author.id != ticket.opener_id:
                ticket.status = "claimed"
                if not ticket.claimed_by:
                    ticket.claimed_by = message.author.id
                    ticket.claimed_by_name = str(message.author)

    @app_commands.command(name="ticket-panel", description="Ticket-Panel im aktuellen Kanal posten (Admin)")
    @app_commands.default_permissions(administrator=True)
    async def ticket_panel_cmd(self, interaction: discord.Interaction) -> None:
        with get_session() as session:
            panel = session.query(TicketPanel).first()
            if not panel:
                panel = TicketPanel()
                session.add(panel)
                session.flush()
            title = panel.title
            description = panel.description
            color = panel.color
            button_label = panel.button_label

        from bot.views.tickets import TicketPanelView

        embed = discord.Embed(title=title, description=description, color=parse_color(color))
        view = TicketPanelView(button_label)
        msg = await interaction.channel.send(embed=embed, view=view)
        with get_session() as session:
            panel = session.query(TicketPanel).first()
            if panel:
                panel.channel_id = interaction.channel_id
                panel.message_id = msg.id
        await interaction.response.send_message("Panel veröffentlicht.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
