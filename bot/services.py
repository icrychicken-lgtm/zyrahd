"""Discord operations shared by cogs, events and the internal API."""

from __future__ import annotations

import asyncio
import io
import re
import unicodedata
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from flask import Flask
from sqlalchemy.exc import IntegrityError

from config import settings
from database.manager import write_audit
from database.models import (
    AnnouncementConfirmation,
    GuildConfig,
    ModerationCase,
    Ticket,
    TicketMessage,
    TicketType,
    WordFilter,
    db,
)


class BotService:
    def __init__(self, bot: discord.Client, web_app: Flask):
        self.bot = bot
        self.web_app = web_app
        self.guild_id = settings.guild_id
        self._message_windows: dict[int, deque[datetime]] = defaultdict(deque)
        self._ticket_locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self._filter_violations: dict[tuple[int, int], int] = defaultdict(int)

    @property
    def guild(self) -> discord.Guild:
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise ValueError("Der konfigurierte Discord-Server ist nicht verbunden.")
        return guild

    def status(self) -> dict[str, Any]:
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return {
                "online": False,
                "guild_name": "Discord nicht verbunden",
                "members": 0,
                "online_members": 0,
                "guild_icon": None,
                "latency_ms": 0,
            }
        return {
            "online": self.bot.is_ready(),
            "guild_name": guild.name,
            "members": guild.member_count or len(guild.members),
            "online_members": sum(
                member.status is not discord.Status.offline for member in guild.members
            ),
            "guild_icon": str(guild.icon.url) if guild.icon else None,
            "latency_ms": round(self.bot.latency * 1000),
        }

    async def resources(self) -> dict[str, Any]:
        guild = self.guild
        bot_member = guild.me
        top_position = bot_member.top_role.position if bot_member else 0
        roles = [
            {
                "id": str(role.id),
                "name": role.name,
                "color": str(role.color),
                "usable": (
                    not role.managed
                    and role.position < top_position
                    and role != guild.default_role
                ),
                "managed": role.managed,
            }
            for role in reversed(guild.roles)
            if role != guild.default_role and not role.managed
        ]
        channel_types = {
            discord.ChannelType.text: "text",
            discord.ChannelType.news: "announcement",
            discord.ChannelType.voice: "voice",
            discord.ChannelType.forum: "forum",
            discord.ChannelType.category: "category",
            discord.ChannelType.stage_voice: "voice",
        }
        channels = [
            {
                "id": str(channel.id),
                "name": channel.name,
                "type": channel_types[channel.type],
                "category": (
                    channel.category.name
                    if getattr(channel, "category", None)
                    else None
                ),
            }
            for channel in guild.channels
            if channel.type in channel_types
        ]
        channels.sort(key=lambda item: (item["type"], item["name"].lower()))
        members = [
            {
                "id": str(member.id),
                "name": member.display_name,
                "username": member.name,
                "avatar": str(member.display_avatar.url),
                "bot": member.bot,
            }
            for member in guild.members
            if not member.bot
        ]
        try:
            bans = [entry async for entry in guild.bans(limit=1000)]
        except discord.HTTPException:
            bans = []
        members.extend(
            {
                "id": str(entry.user.id),
                "name": entry.user.global_name or entry.user.name,
                "username": entry.user.name,
                "avatar": str(entry.user.display_avatar.url),
                "bot": entry.user.bot,
                "banned": True,
            }
            for entry in bans
            if not entry.user.bot
        )
        members.sort(key=lambda item: item["name"].lower())
        return {"roles": roles, "channels": channels, "members": members}

    def ticket_type_options(self) -> list[discord.SelectOption]:
        with self.web_app.app_context():
            values = db.session.scalars(
                db.select(TicketType)
                .where(
                    TicketType.guild_id == str(self.guild_id),
                    TicketType.enabled.is_(True),
                )
                .order_by(TicketType.name)
            ).all()
            return [
                discord.SelectOption(
                    label=value.name[:100],
                    description=value.description[:100] or None,
                    emoji=value.emoji or None,
                    value=str(value.id),
                )
                for value in values
            ]

    def get_ticket_type(self, ticket_type_id: int) -> TicketType | None:
        with self.web_app.app_context():
            return db.session.scalar(
                db.select(TicketType).where(
                    TicketType.id == ticket_type_id,
                    TicketType.guild_id == str(self.guild_id),
                )
            )

    async def create_ticket(
        self,
        ticket_type_id: int,
        creator_id: int,
        creator_name: str,
        answers: dict[str, Any],
    ) -> Ticket:
        lock = self._ticket_locks[(ticket_type_id, creator_id)]
        async with lock:
            return await self._create_ticket_locked(
                ticket_type_id, creator_id, creator_name, answers
            )

    async def _create_ticket_locked(
        self,
        ticket_type_id: int,
        creator_id: int,
        creator_name: str,
        answers: dict[str, Any],
    ) -> Ticket:
        guild = self.guild
        try:
            member = guild.get_member(creator_id) or await guild.fetch_member(
                creator_id
            )
        except discord.NotFound as exc:
            raise ValueError("Du bist nicht mehr Mitglied dieses Servers.") from exc

        with self.web_app.app_context():
            ticket_type = db.session.scalar(
                db.select(TicketType).where(
                    TicketType.id == ticket_type_id,
                    TicketType.guild_id == str(self.guild_id),
                    TicketType.enabled.is_(True),
                )
            )
            if ticket_type is None:
                raise ValueError("Diese Ticket-Art ist nicht mehr verfügbar.")
            open_count = db.session.scalar(
                db.select(db.func.count(Ticket.id)).where(
                    Ticket.guild_id == str(self.guild_id),
                    Ticket.ticket_type_id == ticket_type.id,
                    Ticket.creator_id == str(creator_id),
                    Ticket.status.in_(("creating", "open", "claimed", "waiting")),
                )
            )
            if (open_count or 0) >= ticket_type.max_open_per_user:
                raise ValueError(
                    "Du hast bereits die maximale Anzahl offener Tickets erreicht."
                )
            previous = db.session.scalar(
                db.select(Ticket)
                .where(
                    Ticket.guild_id == str(self.guild_id),
                    Ticket.ticket_type_id == ticket_type.id,
                    Ticket.creator_id == str(creator_id),
                )
                .order_by(Ticket.created_at.desc())
                .limit(1)
            )
            if previous and ticket_type.cooldown_minutes:
                created_at = previous.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                available_at = created_at + timedelta(
                    minutes=ticket_type.cooldown_minutes
                )
                if datetime.now(UTC) < available_at:
                    minutes = max(
                        1, int((available_at - datetime.now(UTC)).total_seconds() / 60)
                    )
                    raise ValueError(
                        f"Bitte warte noch etwa {minutes} Minute(n), bevor du ein "
                        "weiteres Ticket dieser Art öffnest."
                    )
            ticket = Ticket(
                guild_id=str(self.guild_id),
                ticket_type_id=ticket_type.id,
                creator_id=str(creator_id),
                creator_name=creator_name,
                status="creating",
                priority=ticket_type.priority,
                form_answers=answers,
            )
            db.session.add(ticket)
            db.session.flush()
            ticket_number = ticket.id
            category_id = (
                int(ticket_type.category_id) if ticket_type.category_id else None
            )
            support_role_ids = list(ticket_type.support_role_ids or [])
            channel_format = ticket_type.channel_name_format
            greeting = ticket_type.greeting
            color = ticket_type.color
            fields = list(ticket_type.form_fields or [])
            ping_roles = ticket_type.ping_roles
            db.session.commit()

        category = guild.get_channel(category_id) if category_id else None
        if category is not None and not isinstance(category, discord.CategoryChannel):
            category = None
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True,
            )
        support_roles = []
        for role_id in support_role_ids:
            role = guild.get_role(int(role_id))
            if role:
                support_roles.append(role)
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )
        channel_name = channel_format.format(
            number=ticket_number, user=member.display_name
        )
        channel_name = (
            re.sub(r"[^a-z0-9äöüß-]+", "-", channel_name.lower()).strip("-")[:90]
            or f"ticket-{ticket_number}"
        )
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"zyrahd Ticket ZY-{ticket_number:05d} | Ersteller {creator_id}",
                reason=f"Ticket ZY-{ticket_number:05d} erstellt",
            )
        except discord.HTTPException:
            with self.web_app.app_context():
                stored = db.session.get(Ticket, ticket_number)
                if stored:
                    db.session.delete(stored)
                    db.session.commit()
            raise ValueError(
                "Der Ticket-Kanal konnte nicht erstellt werden. Prüfe die Bot-Rechte."
            )

        embed = discord.Embed(
            title=f"{ticket_type.emoji} {ticket_type.name}",
            description=greeting.format(
                mention=member.mention, user=member.display_name
            ),
            color=discord.Color(int(color.lstrip("#"), 16)),
            timestamp=datetime.now(UTC),
        )
        field_map = {field["id"]: field["label"] for field in fields}
        for key, answer in answers.items():
            if answer:
                embed.add_field(
                    name=field_map.get(key, key)[:256],
                    value=str(answer)[:1024],
                    inline=False,
                )
        embed.set_footer(text=f"Ticket ZY-{ticket_number:05d}")
        mentions = (
            " ".join(role.mention for role in support_roles) if ping_roles else ""
        )
        from bot.views import TicketControlView

        try:
            await channel.send(
                content=f"{member.mention} {mentions}".strip(),
                embed=embed,
                view=TicketControlView(self),
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=ping_roles, everyone=False
                ),
            )
            with self.web_app.app_context():
                stored = db.session.get(Ticket, ticket_number)
                if stored is None:
                    raise RuntimeError("Der Ticket-Datensatz ist nicht mehr vorhanden.")
                stored.channel_id = str(channel.id)
                stored.status = "open"
                write_audit(
                    str(self.guild_id),
                    {"id": str(creator_id), "username": creator_name},
                    "Ticket erstellt",
                    "tickets",
                    target=f"ZY-{ticket_number:05d}",
                    after={
                        "ticket_type_id": ticket_type_id,
                        "channel_id": str(channel.id),
                    },
                )
                db.session.commit()
                ticket = stored
        except Exception:
            try:
                await channel.delete(reason="Unvollständiges Ticket – Rollback")
            except discord.HTTPException:
                pass
            with self.web_app.app_context():
                db.session.rollback()
                stored = db.session.get(Ticket, ticket_number)
                if stored:
                    db.session.delete(stored)
                    db.session.commit()
            raise
        return ticket

    def ticket_for_channel(self, channel_id: int | None) -> Ticket | None:
        if channel_id is None:
            return None
        with self.web_app.app_context():
            return db.session.scalar(
                db.select(Ticket).where(Ticket.channel_id == str(channel_id))
            )

    def claim_ticket(self, channel_id: int | None, member: discord.Member) -> str:
        with self.web_app.app_context():
            ticket = db.session.scalar(
                db.select(Ticket).where(Ticket.channel_id == str(channel_id))
            )
            if ticket is None or ticket.status in {"closed", "archived"}:
                raise ValueError("Dieses Ticket ist nicht aktiv.")
            allowed_roles = set(ticket.ticket_type.support_role_ids or [])
            member_roles = {str(role.id) for role in member.roles}
            if not member.guild_permissions.manage_messages and not (
                allowed_roles & member_roles
            ):
                raise ValueError("Du gehörst nicht zum zuständigen Ticket-Team.")
            if ticket.claimed_by_id and ticket.claimed_by_id != str(member.id):
                raise ValueError(
                    f"Das Ticket wurde bereits von {ticket.claimed_by_name} übernommen."
                )
            ticket.claimed_by_id = str(member.id)
            ticket.claimed_by_name = member.display_name
            ticket.status = "claimed"
            db.session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=str(member.id),
                    author_name=member.display_name,
                    content=f"{member.display_name} hat das Ticket übernommen.",
                    source="discord",
                    is_system=True,
                )
            )
            db.session.commit()
            return f"🙋 {member.mention} hat das Ticket übernommen."

    async def close_ticket_by_channel(
        self, channel_id: int | None, actor_id: int, reason: str
    ) -> None:
        ticket = self.ticket_for_channel(channel_id)
        if ticket is None:
            raise ValueError("Dieses Ticket wurde nicht gefunden.")
        await self.close_ticket(ticket.id, actor_id, reason)

    async def close_ticket(self, ticket_id: int, actor_id: int, reason: str) -> None:
        with self.web_app.app_context():
            ticket = db.session.scalar(
                db.select(Ticket).where(
                    Ticket.id == ticket_id, Ticket.guild_id == str(self.guild_id)
                )
            )
            if ticket is None:
                raise ValueError("Ticket nicht gefunden.")
            if ticket.status in {"closed", "archived"}:
                raise ValueError("Dieses Ticket ist bereits geschlossen.")
            channel_id = int(ticket.channel_id) if ticket.channel_id else None
            creator_id = int(ticket.creator_id)
            transcript_id = (
                int(ticket.ticket_type.transcript_channel_id)
                if ticket.ticket_type.transcript_channel_id
                else None
            )
            number = ticket.id

        guild = self.guild
        channel = guild.get_channel(channel_id) if channel_id else None
        creator = guild.get_member(creator_id)
        if isinstance(channel, discord.TextChannel):
            try:
                if creator:
                    await channel.set_permissions(
                        creator,
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                        reason=f"Ticket ZY-{number:05d} geschlossen",
                    )
                if not channel.name.startswith("closed-"):
                    await channel.edit(
                        name=f"closed-{channel.name}"[:100],
                        reason=f"Ticket geschlossen: {reason}",
                    )
            except discord.HTTPException as exc:
                raise ValueError(
                    "Discord konnte den Ticket-Kanal nicht schließen."
                ) from exc

        with self.web_app.app_context():
            ticket = db.session.get(Ticket, ticket_id)
            if ticket is None:
                raise ValueError("Ticket nicht gefunden.")
            ticket.status = "closed"
            ticket.closed_at = datetime.now(UTC)
            ticket.close_reason = reason
            db.session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=str(actor_id),
                    author_name="System",
                    content=f"Ticket geschlossen: {reason}",
                    source="system",
                    is_system=True,
                )
            )
            db.session.commit()
            messages = db.session.scalars(
                db.select(TicketMessage)
                .where(TicketMessage.ticket_id == ticket.id)
                .order_by(TicketMessage.created_at)
            ).all()
            transcript = "\n".join(
                f"[{message.created_at.isoformat()}] {message.author_name}: "
                f"{message.content}"
                for message in messages
            )

        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    embed=discord.Embed(
                        title="🔒 Ticket geschlossen",
                        description=f"**Grund:** {reason}",
                        color=discord.Color.dark_grey(),
                        timestamp=datetime.now(UTC),
                    )
                )
            except discord.HTTPException:
                pass
        transcript_channel = guild.get_channel(transcript_id) if transcript_id else None
        if isinstance(transcript_channel, discord.TextChannel):
            file = discord.File(
                io.BytesIO(transcript.encode("utf-8")),
                filename=f"ticket-ZY-{number:05d}.txt",
            )
            try:
                await transcript_channel.send(
                    f"Transcript für **ZY-{number:05d}**", file=file
                )
            except discord.HTTPException:
                pass

    async def post_web_message(
        self,
        ticket_id: int,
        author_id: str,
        author_name: str,
        author_avatar: str | None,
        content: str,
    ) -> dict[str, Any]:
        with self.web_app.app_context():
            ticket = db.session.get(Ticket, ticket_id)
            if ticket is None or ticket.guild_id != str(self.guild_id):
                raise ValueError("Ticket nicht gefunden.")
            if ticket.status in {"closed", "archived"} or not ticket.channel_id:
                raise ValueError("Dieses Ticket ist nicht mehr aktiv.")
            channel_id = int(ticket.channel_id)
            stored_message = TicketMessage(
                ticket_id=ticket_id,
                author_id=author_id,
                author_name=author_name,
                author_avatar=author_avatar,
                content=content,
                source="web",
            )
            db.session.add(stored_message)
            db.session.commit()
            stored_message_id = stored_message.id
        channel = self.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            with self.web_app.app_context():
                pending = db.session.get(TicketMessage, stored_message_id)
                if pending:
                    db.session.delete(pending)
                    db.session.commit()
            raise ValueError("Der Ticket-Kanal existiert nicht mehr.")
        embed = discord.Embed(
            description=content,
            color=discord.Color.from_str("#8b5cf6"),
            timestamp=datetime.now(UTC),
        )
        embed.set_author(name=f"{author_name} · Web-Dashboard", icon_url=author_avatar)
        try:
            message = await channel.send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            with self.web_app.app_context():
                pending = db.session.get(TicketMessage, stored_message_id)
                if pending:
                    db.session.delete(pending)
                    db.session.commit()
            raise
        return {"message_id": str(message.id)}

    async def mirror_discord_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        with self.web_app.app_context():
            ticket = db.session.scalar(
                db.select(Ticket).where(Ticket.channel_id == str(message.channel.id))
            )
            if ticket is None:
                return
            db.session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=str(message.author.id),
                    author_name=message.author.display_name,
                    author_avatar=str(message.author.display_avatar.url),
                    content=message.content,
                    source="discord",
                    attachments=[
                        {
                            "name": attachment.filename,
                            "url": attachment.url,
                            "content_type": attachment.content_type or "",
                        }
                        for attachment in message.attachments
                    ],
                )
            )
            db.session.commit()

    async def moderate(self, payload: dict[str, Any]) -> dict[str, Any]:
        guild = self.guild
        try:
            user_id = int(payload["user_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Ungültige Discord-Benutzer-ID.") from exc
        action = payload["action"]
        reason = payload["reason"]
        if action not in {"warn", "timeout", "untimeout", "kick", "ban", "unban"}:
            raise ValueError("Unbekannte Moderationsaktion.")
        member = guild.get_member(user_id)
        if action != "unban" and member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound as exc:
                raise ValueError(
                    "Der Benutzer wurde auf dem Server nicht gefunden."
                ) from exc
        audit_reason = f"{reason} | Moderator: {payload['moderator_name']}"
        with self.web_app.app_context():
            case = ModerationCase(
                guild_id=str(self.guild_id),
                user_id=str(user_id),
                user_name=getattr(member, "display_name", str(user_id)),
                moderator_id=str(payload["moderator_id"]),
                moderator_name=payload["moderator_name"],
                action=action,
                reason=reason,
                duration_minutes=payload.get("duration_minutes"),
                status="pending",
            )
            db.session.add(case)
            db.session.commit()
            case_id = case.id

        def discard_pending_case() -> None:
            with self.web_app.app_context():
                pending = db.session.get(ModerationCase, case_id)
                if pending and pending.status == "pending":
                    db.session.delete(pending)
                    db.session.commit()

        try:
            if action == "warn":
                try:
                    await member.send(f"⚠️ Verwarnung auf **{guild.name}**: {reason}")
                except discord.HTTPException:
                    pass
            elif action == "timeout":
                until = datetime.now(UTC) + timedelta(
                    minutes=int(payload["duration_minutes"])
                )
                await member.timeout(until, reason=audit_reason)
            elif action == "untimeout":
                await member.timeout(None, reason=audit_reason)
            elif action == "kick":
                await member.kick(reason=audit_reason)
            elif action == "ban":
                await member.ban(reason=audit_reason, delete_message_seconds=0)
            elif action == "unban":
                await guild.unban(discord.Object(id=user_id), reason=audit_reason)
        except discord.Forbidden as exc:
            discard_pending_case()
            raise ValueError(
                "Dem Bot fehlen Rechte oder seine Rolle steht unter der Zielrolle."
            ) from exc
        except discord.HTTPException as exc:
            discard_pending_case()
            raise ValueError("Discord konnte die Moderation nicht ausführen.") from exc

        with self.web_app.app_context():
            case = db.session.get(ModerationCase, case_id)
            if case is None:
                raise RuntimeError("Der Moderationsfall wurde nicht gespeichert.")
            case.status = "active"
            write_audit(
                str(self.guild_id),
                {
                    "id": payload["moderator_id"],
                    "username": payload["moderator_name"],
                },
                f"Moderation: {action}",
                "moderation",
                target=str(user_id),
                after={"case_id": case.id, "reason": reason},
            )
            db.session.commit()
            return {"case": case.to_dict()}

    async def send_embed(self, payload: dict[str, Any]) -> dict[str, str]:
        try:
            channel_id = int(payload["channel_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Ungültiger Discord-Kanal.") from exc
        channel = self.guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise ValueError("Der gewählte Textkanal wurde nicht gefunden.")
        embed = discord.Embed(
            title=payload.get("title") or None,
            description=payload.get("description") or None,
            color=discord.Color(int(payload.get("color", "#8b5cf6")[1:], 16)),
            timestamp=datetime.now(UTC),
        )
        if payload.get("footer"):
            embed.set_footer(text=payload["footer"])
        if payload.get("image_url"):
            embed.set_image(url=payload["image_url"])
        if payload.get("thumbnail_url"):
            embed.set_thumbnail(url=payload["thumbnail_url"])
        message = await channel.send(
            content=payload.get("content") or None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return {"message_id": str(message.id), "channel_id": str(channel.id)}

    async def publish_ticket_panel(self, channel_id: int) -> dict[str, str]:
        channel = self.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Bitte wähle einen Textkanal.")
        from bot.views import TicketPanelView

        embed = discord.Embed(
            title="🎫 Support-Center",
            description=(
                "Benötigst du Hilfe oder möchtest du Kontakt mit unserem Team "
                "aufnehmen?\n\nKlicke auf **Ticket erstellen** und wähle den "
                "passenden Bereich."
            ),
            color=discord.Color.from_str("#8b5cf6"),
        )
        message = await channel.send(embed=embed, view=TicketPanelView(self))
        return {"message_id": str(message.id)}

    async def publish_verify(self) -> dict[str, str]:
        with self.web_app.app_context():
            guild_config = db.session.scalar(
                db.select(GuildConfig).where(GuildConfig.guild_id == str(self.guild_id))
            )
            if guild_config is None:
                raise ValueError("Die Serverkonfiguration fehlt.")
            verify = dict(guild_config.verify or {})
        channel_id = verify.get("channel_id")
        channel = self.guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Bitte konfiguriere zuerst einen Verify-Kanal.")
        from bot.views import VerifyView

        embed = discord.Embed(
            title=verify.get("title") or "Verifizierung",
            description=verify.get("description") or "Klicke auf den Button.",
            color=discord.Color(int(verify.get("color", "#8b5cf6")[1:], 16)),
        )
        message = await channel.send(
            embed=embed,
            view=VerifyView(
                self,
                verify.get("button_text", "Verifizieren"),
                verify.get("button_emoji", "✅"),
            ),
        )
        return {"message_id": str(message.id)}

    async def verify_member(self, member: discord.Member) -> str:
        with self.web_app.app_context():
            guild_config = db.session.scalar(
                db.select(GuildConfig).where(GuildConfig.guild_id == str(self.guild_id))
            )
            if guild_config is None:
                raise ValueError("Die Serverkonfiguration fehlt.")
            verify = dict(guild_config.verify or {})
        if not verify.get("enabled"):
            raise ValueError("Die Verifizierung ist aktuell deaktiviert.")
        account_age = datetime.now(UTC) - member.created_at
        minimum_days = int(verify.get("minimum_account_days", 0))
        if account_age < timedelta(days=minimum_days):
            raise ValueError(
                f"Dein Discord-Konto muss mindestens {minimum_days} Tage alt sein."
            )
        role_id = verify.get("role_id")
        role = member.guild.get_role(int(role_id)) if role_id else None
        if role is None:
            raise ValueError("Die Verifizierungsrolle ist nicht korrekt konfiguriert.")
        remove_roles = [
            found
            for value in verify.get("remove_role_ids", [])
            if (found := member.guild.get_role(int(value))) is not None
        ]
        try:
            await member.add_roles(role, reason="zyrahd.net Verifizierung")
            if remove_roles:
                await member.remove_roles(
                    *remove_roles, reason="zyrahd.net Verifizierung"
                )
            if verify.get("dm_enabled"):
                try:
                    await member.send(
                        f"✅ Du wurdest auf **{member.guild.name}** verifiziert."
                    )
                except discord.HTTPException:
                    pass
        except discord.Forbidden as exc:
            raise ValueError(
                "Der Bot kann die Verifizierungsrolle nicht vergeben."
            ) from exc
        return f"Du wurdest erfolgreich als **{role.name}** verifiziert."

    async def welcome_member(self, member: discord.Member) -> None:
        with self.web_app.app_context():
            guild_config = db.session.scalar(
                db.select(GuildConfig).where(GuildConfig.guild_id == str(self.guild_id))
            )
            if guild_config is None:
                return
            welcome = dict(guild_config.welcome or {})
        if not welcome.get("enabled"):
            return
        replacements = {
            "{user}": str(member),
            "{username}": member.name,
            "{display_name}": member.display_name,
            "{mention}": member.mention,
            "{server}": member.guild.name,
            "{member_count}": str(member.guild.member_count or 0),
            "{created_at}": discord.utils.format_dt(member.created_at, "D"),
            "{joined_at}": discord.utils.format_dt(
                member.joined_at or datetime.now(UTC), "D"
            ),
        }

        def replace(value: str) -> str:
            for key, replacement in replacements.items():
                value = value.replace(key, replacement)
            return value

        roles = [
            role
            for role_id in welcome.get("role_ids", [])
            if (role := member.guild.get_role(int(role_id))) is not None
        ]
        if roles:
            try:
                await member.add_roles(*roles, reason="Automatische Willkommensrollen")
            except discord.Forbidden:
                pass
        message_text = replace(welcome.get("message", "Willkommen {mention}!"))
        channel_id = welcome.get("channel_id")
        channel = member.guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            if welcome.get("embed", True):
                embed = discord.Embed(
                    title=replace(welcome.get("title", "Willkommen!")),
                    description=message_text,
                    color=discord.Color(int(welcome.get("color", "#8b5cf6")[1:], 16)),
                    timestamp=datetime.now(UTC),
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await channel.send(embed=embed)
            else:
                await channel.send(
                    message_text,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
        if welcome.get("dm_enabled"):
            try:
                await member.send(message_text)
            except discord.HTTPException:
                pass

    async def enforce_security(self, message: discord.Message) -> bool:
        if (
            message.author.bot
            or not message.guild
            or not isinstance(message.author, discord.Member)
        ):
            return False
        if message.author.guild_permissions.manage_messages:
            return False
        with self.web_app.app_context():
            guild_config = db.session.scalar(
                db.select(GuildConfig).where(GuildConfig.guild_id == str(self.guild_id))
            )
            security = dict(guild_config.security or {}) if guild_config else {}
            filters = db.session.scalars(
                db.select(WordFilter).where(
                    WordFilter.guild_id == str(self.guild_id),
                    WordFilter.enabled.is_(True),
                )
            ).all()
        if str(message.channel.id) in security.get("exempt_channel_ids", []):
            return False
        author_roles = {str(role.id) for role in message.author.roles}
        if author_roles & set(security.get("exempt_role_ids", [])):
            return False

        violation_action: str | None = None
        response = ""
        timeout_minutes = 10
        log_channel_id: str | None = None
        normalized = normalize_text(message.content)
        for item in filters:
            if str(message.channel.id) in (item.exempt_channel_ids or []):
                continue
            if author_roles & set(item.exempt_role_ids or []):
                continue
            phrase = item.phrase if item.case_sensitive else item.phrase.lower()
            content = (
                message.content if item.case_sensitive else message.content.lower()
            )
            normalized_phrase = normalize_text(item.phrase)
            matches = (
                content.strip() == phrase
                if item.match_type == "exact"
                else phrase in content or normalized_phrase in normalized
            )
            if matches:
                key = (message.author.id, item.id)
                violations = self._filter_violations[key] + 1
                self._filter_violations[key] = violations
                threshold = max(1, item.threshold)
                if violations >= threshold:
                    violation_action = item.action
                    self._filter_violations[key] = 0
                else:
                    violation_action = "delete"
                response = item.response
                if not response and violations < threshold:
                    response = (
                        f"Regelverstoß {violations}/{threshold}. "
                        "Bitte beachte die Serverregeln."
                    )
                timeout_minutes = item.timeout_minutes
                log_channel_id = item.log_channel_id
                break

        if (
            not violation_action
            and security.get("anti_invites")
            and re.search(
                r"(discord\.gg/|discord(?:app)?\.com/invite/)",
                message.content,
                re.IGNORECASE,
            )
        ):
            violation_action = "delete"
            response = "Discord-Einladungen sind hier nicht erlaubt."
        if (
            not violation_action
            and security.get("anti_links")
            and re.search(r"https?://\S+", message.content, re.IGNORECASE)
        ):
            violation_action = "delete"
            response = "Links sind hier nicht erlaubt."
        if not violation_action and security.get("anti_caps"):
            letters = [
                character for character in message.content if character.isalpha()
            ]
            caps = sum(character.isupper() for character in letters)
            if len(letters) >= 10 and caps / len(letters) * 100 >= int(
                security.get("caps_percentage", 75)
            ):
                violation_action = "delete"
                response = "Bitte verwende weniger Großbuchstaben."
        if not violation_action and len(message.mentions) > int(
            security.get("mention_limit", 5)
        ):
            violation_action = "timeout"
            response = "Zu viele Erwähnungen in einer Nachricht."
        if not violation_action and security.get("anti_spam"):
            now = datetime.now(UTC)
            window = self._message_windows[message.author.id]
            window.append(now)
            span = timedelta(seconds=int(security.get("spam_seconds", 8)))
            while window and now - window[0] > span:
                window.popleft()
            if len(window) >= int(security.get("spam_messages", 6)):
                violation_action = "timeout"
                timeout_minutes = 5
                response = "Bitte sende Nachrichten langsamer."
                window.clear()
        if not violation_action:
            return False

        try:
            await message.delete()
        except discord.HTTPException:
            pass
        if violation_action == "timeout":
            try:
                await message.author.timeout(
                    datetime.now(UTC) + timedelta(minutes=timeout_minutes),
                    reason="Automod von zyrahd.net",
                )
            except discord.HTTPException:
                pass
        elif violation_action == "warn":
            try:
                await message.author.send(
                    f"⚠️ Automod-Verwarnung auf **{message.guild.name}**: "
                    f"{response or 'Bitte beachte die Serverregeln.'}"
                )
            except discord.HTTPException:
                pass
        elif violation_action == "kick":
            try:
                await message.author.kick(reason="Wortfilter von zyrahd.net")
            except discord.HTTPException:
                pass
        elif violation_action == "ban":
            try:
                await message.author.ban(
                    reason="Wortfilter von zyrahd.net", delete_message_seconds=0
                )
            except discord.HTTPException:
                pass
        if log_channel_id:
            log_channel = message.guild.get_channel(int(log_channel_id))
            if isinstance(log_channel, discord.TextChannel):
                try:
                    await log_channel.send(
                        embed=discord.Embed(
                            title="Automod-Ereignis",
                            description=(
                                f"**Mitglied:** {message.author.mention}\n"
                                f"**Kanal:** {message.channel.mention}\n"
                                f"**Aktion:** {violation_action}"
                            ),
                            color=discord.Color.orange(),
                            timestamp=datetime.now(UTC),
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    pass
        if response:
            try:
                await message.channel.send(
                    f"{message.author.mention} {response}",
                    delete_after=8,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                pass
        return True

    async def publish_announcement(self, payload: dict[str, Any]) -> dict[str, str]:
        channel = self.guild.get_channel(int(payload["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Der gewählte Ankündigungskanal wurde nicht gefunden.")
        priority_colors = {
            "normal": discord.Color.from_str("#8b5cf6"),
            "important": discord.Color.orange(),
            "urgent": discord.Color.red(),
        }
        embed = discord.Embed(
            title=payload["title"],
            description=payload["content"],
            color=priority_colors.get(
                payload.get("priority"), priority_colors["normal"]
            ),
            timestamp=datetime.now(UTC),
        )
        embed.set_footer(text="Interne Team-Ankündigung")
        roles = [
            role
            for role_id in payload.get("target_role_ids", [])
            if (role := self.guild.get_role(int(role_id))) is not None
        ]
        content = " ".join(role.mention for role in roles)
        view = None
        if payload.get("require_confirmation"):
            from bot.views import AnnouncementConfirmView

            view = AnnouncementConfirmView(self, int(payload["announcement_id"]))
        message = await channel.send(
            content=content or None,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                roles=True, users=False, everyone=False
            ),
        )
        return {"message_id": str(message.id)}

    def confirm_announcement(
        self, announcement_id: int, member: discord.Member | discord.User
    ) -> bool:
        with self.web_app.app_context():
            existing = db.session.scalar(
                db.select(AnnouncementConfirmation).where(
                    AnnouncementConfirmation.announcement_id == announcement_id,
                    AnnouncementConfirmation.user_id == str(member.id),
                )
            )
            if existing:
                return False
            db.session.add(
                AnnouncementConfirmation(
                    announcement_id=announcement_id,
                    user_id=str(member.id),
                    user_name=member.display_name,
                )
            )
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return False
            return True


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if character.isalnum())
