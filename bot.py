"""Discord bot entry point and the dashboard-to-bot service surface."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

# ``bot.py`` stays the requested entry module while also exposing the modular
# ``bot/`` tree as submodules (cogs, views and utilities).
__path__ = [str(Path(__file__).with_name("bot"))]

from bot import runtime
from bot.utils.tickets import create_ticket, send_web_message
from bot.views.announcement import AnnouncementConfirmView
from bot.views.ticket_actions import TicketActionsView
from bot.views.ticket_panel import TicketPanelView
from bot.views.verify import VerifyView
from config import settings
from database.manager import get_setting, session_scope
from database.models import ModerationCase, TeamAnnouncement, Ticket


log = logging.getLogger("zyrahd.bot")
EXTENSIONS = (
    "bot.cogs.tickets",
    "bot.cogs.security",
    "bot.cogs.welcome",
    "bot.cogs.moderation",
)


class ZyraBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.moderation = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=True
            ),
        )
        self.synced_commands = 0

    async def setup_hook(self) -> None:
        runtime.register(self)
        for extension in EXTENSIONS:
            await self.load_extension(extension)
            log.info("Modul geladen: %s", extension)
        self.add_view(TicketPanelView())
        self.add_view(TicketActionsView())
        self.add_view(VerifyView())
        self.add_view(AnnouncementConfirmView())
        if settings.guild_id:
            guild = discord.Object(id=settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            self.synced_commands = len(synced)
            log.info("%d Slash-Commands synchronisiert.", self.synced_commands)
        else:
            log.warning("Keine GUILD_ID gesetzt; Slash-Commands wurden nicht synchronisiert.")

    async def on_ready(self) -> None:
        guild = self.get_guild(settings.guild_id)
        log.info("Discord-Anmeldung erfolgreich als %s.", self.user)
        if guild:
            log.info("Server geladen: %s (%s).", guild.name, guild.id)
        else:
            log.error("Der konfigurierte Server %s wurde nicht gefunden.", settings.guild_id)

    async def close(self) -> None:
        runtime.unregister()
        await super().close()

    def configured_guild(self) -> discord.Guild:
        guild = self.get_guild(settings.guild_id)
        if guild is None:
            raise ValueError("Der konfigurierte Discord-Server ist nicht verbunden.")
        return guild

    async def dashboard_snapshot(self, user_id: int | None = None) -> dict[str, Any]:
        guild = self.configured_guild()
        me = guild.me
        highest_bot_role = me.top_role.position if me else 0
        roles = [
            {
                "id": str(role.id),
                "name": role.name,
                "color": str(role.color),
                "position": role.position,
                "managed": role.managed,
                "usable": not role.managed
                and role != guild.default_role
                and role.position < highest_bot_role,
            }
            for role in sorted(guild.roles, key=lambda item: item.position, reverse=True)
            if role != guild.default_role
        ]
        channels = []
        for channel in sorted(guild.channels, key=lambda item: item.position):
            if isinstance(channel, discord.CategoryChannel):
                kind = "category"
            elif isinstance(channel, discord.ForumChannel):
                kind = "forum"
            elif isinstance(channel, discord.VoiceChannel):
                kind = "voice"
            elif isinstance(channel, discord.TextChannel):
                kind = "announcement" if channel.is_news() else "text"
            else:
                continue
            channels.append(
                {
                    "id": str(channel.id),
                    "name": channel.name,
                    "type": kind,
                    "category": channel.category.name
                    if getattr(channel, "category", None)
                    else None,
                }
            )
        member_data = None
        if user_id:
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    member = None
            if member:
                member_data = {
                    "id": str(member.id),
                    "display_name": member.display_name,
                    "avatar": member.display_avatar.url,
                    "role_ids": [str(role.id) for role in member.roles],
                    "administrator": member.guild_permissions.administrator,
                }
        return {
            "ready": self.is_ready(),
            "latency_ms": round(self.latency * 1000),
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "icon": guild.icon.url if guild.icon else None,
                "member_count": guild.member_count or len(guild.members),
                "online_count": sum(
                    member.status != discord.Status.offline for member in guild.members
                ),
                "owner_id": str(guild.owner_id),
            },
            "roles": roles,
            "channels": channels,
            "member": member_data,
        }

    async def create_dashboard_ticket(
        self,
        *,
        ticket_type_id: int,
        creator_id: int,
        creator_name: str,
        answers: dict[str, Any],
    ) -> dict[str, Any]:
        return await create_ticket(
            self,
            guild_id=settings.guild_id,
            ticket_type_id=ticket_type_id,
            creator_id=creator_id,
            creator_name=creator_name,
            answers=answers,
        )

    async def send_dashboard_ticket_message(
        self, ticket_id: int, author_id: int, author_name: str, content: str
    ) -> dict[str, Any]:
        return await send_web_message(
            self, ticket_id, author_id, author_name, content
        )

    async def change_ticket_status(
        self,
        ticket_id: int,
        status: str,
        actor_id: int,
        actor_name: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if status not in {"open", "claimed", "waiting", "closed", "archived"}:
            raise ValueError("Ungültiger Ticket-Status.")
        with session_scope() as db:
            ticket = db.get(Ticket, ticket_id)
            if not ticket:
                raise ValueError("Ticket nicht gefunden.")
            previous = ticket.status
            ticket.status = status
            ticket.updated_at = datetime.now(timezone.utc)
            if status == "claimed":
                ticket.assigned_to_id = str(actor_id)
                ticket.assigned_to_name = actor_name
            if status == "closed":
                ticket.closed_at = ticket.updated_at
                ticket.closed_reason = reason or "Über das Dashboard geschlossen"
            channel_id = int(ticket.discord_channel_id) if ticket.discord_channel_id else 0
            creator_id = int(ticket.creator_id)
        channel = self.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            member = channel.guild.get_member(creator_id)
            if member and status in {"closed", "archived"}:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    reason=f"Ticket #{ticket_id} via Dashboard geschlossen",
                )
            elif member and status in {"open", "claimed", "waiting"}:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    reason=f"Ticket #{ticket_id} via Dashboard geöffnet",
                )
            await channel.send(
                f"**Status:** `{previous}` → `{status}` · geändert von **{actor_name}**"
            )
        return {"id": ticket_id, "status": status}

    async def publish_panel(self, panel: str, channel_id: int) -> dict[str, str]:
        channel = self.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Bitte wähle einen Text- oder Ankündigungskanal.")
        if panel == "ticket":
            config = get_setting(str(settings.guild_id), "ticket_panel", {})
            embed = discord.Embed(
                title=str(config.get("title", "Support-Center"))[:256],
                description=str(
                    config.get(
                        "description",
                        "Benötigst du Hilfe? Klicke auf **Ticket erstellen** und wähle den passenden Bereich.",
                    )
                )[:4000],
                color=int(str(config.get("color", "#7c5cff")).lstrip("#"), 16),
            )
            message = await channel.send(embed=embed, view=TicketPanelView())
        elif panel == "verify":
            config = get_setting(str(settings.guild_id), "verify", {})
            embed = discord.Embed(
                title=str(config.get("title", "Verifizierung"))[:256],
                description=str(
                    config.get(
                        "description",
                        "Bestätige mit dem Button, dass du Teil dieser Community sein möchtest.",
                    )
                )[:4000],
                color=int(str(config.get("color", "#7c5cff")).lstrip("#"), 16),
            )
            message = await channel.send(embed=embed, view=VerifyView())
        else:
            raise ValueError("Unbekannter Panel-Typ.")
        return {"message_id": str(message.id), "channel_id": str(channel.id)}

    async def send_designed_embed(self, payload: dict[str, Any]) -> dict[str, str]:
        channel = self.get_channel(int(payload.get("channel_id", 0)))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Bitte wähle einen gültigen Textkanal.")
        content = str(payload.get("content", "")).strip()[:2000] or None
        title = str(payload.get("title", "")).strip()[:256]
        description = str(payload.get("description", "")).strip()[:4000]
        embed = None
        if title or description:
            embed = discord.Embed(
                title=title or None,
                description=description or None,
                color=int(str(payload.get("color", "#7c5cff")).lstrip("#"), 16),
                timestamp=datetime.now(timezone.utc)
                if payload.get("timestamp")
                else None,
            )
            if payload.get("footer"):
                embed.set_footer(text=str(payload["footer"])[:2048])
            if payload.get("thumbnail"):
                embed.set_thumbnail(url=str(payload["thumbnail"]))
            if payload.get("image"):
                embed.set_image(url=str(payload["image"]))
            for field in list(payload.get("fields", []))[:25]:
                embed.add_field(
                    name=str(field.get("name", "Feld"))[:256],
                    value=str(field.get("value", "–"))[:1024],
                    inline=bool(field.get("inline")),
                )
        if not content and embed is None:
            raise ValueError("Die Nachricht benötigt Text oder ein Embed.")
        view = discord.ui.View(timeout=None)
        for button in list(payload.get("buttons", []))[:5]:
            url = str(button.get("url", ""))
            if url.startswith(("https://", "http://")):
                view.add_item(
                    discord.ui.Button(
                        label=str(button.get("label", "Link"))[:80],
                        url=url,
                        emoji=button.get("emoji") or None,
                    )
                )
        message = await channel.send(
            content=content,
            embed=embed,
            view=view if view.children else None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return {"message_id": str(message.id), "channel_id": str(channel.id)}

    async def publish_announcement(self, announcement_id: int) -> dict[str, str]:
        with session_scope() as db:
            item = db.get(TeamAnnouncement, announcement_id)
            if not item:
                raise ValueError("Ankündigung nicht gefunden.")
            channel_id = int(item.channel_id)
            title = item.title
            body = item.message
            priority = item.priority
            role_ids = item.decode(item.target_role_ids_json, [])
            confirmation = item.require_confirmation
        channel = self.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Der Zielkanal ist nicht verfügbar.")
        colors = {"normal": 0x7C5CFF, "important": 0xF4B860, "critical": 0xFF5C7A}
        embed = discord.Embed(
            title=title,
            description=body,
            color=colors.get(priority, 0x7C5CFF),
            timestamp=datetime.now(timezone.utc),
        )
        roles = [channel.guild.get_role(int(role_id)) for role_id in role_ids]
        roles = [role for role in roles if role]
        content = " ".join(role.mention for role in roles) or None
        message = await channel.send(
            content=content,
            embed=embed,
            view=AnnouncementConfirmView() if confirmation else None,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        with session_scope() as db:
            item = db.get(TeamAnnouncement, announcement_id)
            if item:
                item.published_at = datetime.now(timezone.utc)
                item.discord_message_id = str(message.id)
        return {"message_id": str(message.id), "channel_id": str(channel.id)}

    async def execute_moderation(
        self,
        *,
        action: str,
        user_id: int,
        moderator_id: int,
        moderator_name: str,
        reason: str,
        duration_minutes: int | None = None,
    ) -> dict[str, Any]:
        guild = self.configured_guild()
        try:
            user = await self.fetch_user(user_id)
        except discord.NotFound as exc:
            raise ValueError("Discord-Benutzer nicht gefunden.") from exc
        member = guild.get_member(user_id)
        if action in {"warn", "timeout", "kick"} and member is None:
            raise ValueError("Dieser Benutzer ist nicht auf dem Server.")
        if action == "timeout":
            minutes = max(1, min(40320, int(duration_minutes or 10)))
            await member.timeout(timedelta(minutes=minutes), reason=reason)
        elif action == "kick":
            await member.kick(reason=reason)
        elif action == "ban":
            await guild.ban(user, reason=reason, delete_message_seconds=0)
        elif action != "warn":
            raise ValueError("Diese Moderationsaktion wird nicht unterstützt.")
        with session_scope() as db:
            row = ModerationCase(
                guild_id=str(guild.id),
                user_id=str(user.id),
                user_name=str(user),
                moderator_id=str(moderator_id),
                moderator_name=moderator_name,
                action=action,
                reason=reason,
                duration_minutes=duration_minutes if action == "timeout" else None,
            )
            db.add(row)
            db.flush()
            case_id = row.id
        return {"id": case_id, "action": action, "user_id": str(user.id)}


def create_bot() -> ZyraBot:
    return ZyraBot()
