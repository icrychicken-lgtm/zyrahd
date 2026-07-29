"""Interne HTTP-API für die Kommunikation zwischen Dashboard und Bot."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aiohttp import web
import discord

import config
from bot.utils.discord_cache import get_cached, invalidate, set_cached
from bot.utils.helpers import build_embed_from_dict, parse_color
from database.manager import get_session
from database.models import ModCase, Ticket, TicketMessage, TicketType

logger = logging.getLogger("zyrahd.internal_api")


def _auth_ok(request: web.Request) -> bool:
    secret = request.headers.get("X-Internal-Secret", "")
    return bool(secret) and secret == config.INTERNAL_API_SECRET


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _ok(data: Any = None, **extra) -> web.Response:
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return web.json_response(payload)


class InternalAPI:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        r = self.app.router
        r.add_get("/health", self.health)
        r.add_get("/guild", self.guild_info)
        r.add_get("/roles", self.list_roles)
        r.add_get("/channels", self.list_channels)
        r.add_post("/cache/invalidate", self.invalidate_cache)
        r.add_post("/panels/ticket", self.publish_ticket_panel)
        r.add_post("/panels/verify", self.publish_verify_panel)
        r.add_post("/embeds/send", self.send_embed)
        r.add_post("/embeds/edit", self.edit_embed)
        r.add_post("/moderation/action", self.moderation_action)
        r.add_post("/roles/assign", self.assign_role)
        r.add_post("/roles/remove", self.remove_role)
        r.add_post("/tickets/create", self.create_ticket)
        r.add_post("/tickets/message", self.send_ticket_message)
        r.add_post("/tickets/action", self.ticket_action)
        r.add_post("/announcements/publish", self.publish_announcement)
        r.add_get("/bot/status", self.bot_status)
        r.add_get("/member/{user_id}", self.member_info)
        r.add_post("/settings/reload", self.reload_settings)

    async def _guard(self, request: web.Request):
        if not _auth_ok(request):
            raise web.HTTPUnauthorized(text="Unauthorized")

    async def health(self, request: web.Request) -> web.Response:
        await self._guard(request)
        return _ok({"status": "ok", "bot_ready": self.bot.is_ready()})

    async def bot_status(self, request: web.Request) -> web.Response:
        await self._guard(request)
        guild = self.bot.get_guild(config.GUILD_ID) if config.GUILD_ID else None
        online = 0
        if guild:
            online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        return _ok(
            {
                "ready": self.bot.is_ready(),
                "user": str(self.bot.user) if self.bot.user else None,
                "latency_ms": round(self.bot.latency * 1000, 1) if self.bot.latency else 0,
                "guild_id": config.GUILD_ID,
                "guild_name": guild.name if guild else None,
                "member_count": guild.member_count if guild else 0,
                "online_count": online,
                "icon_url": str(guild.icon.url) if guild and guild.icon else None,
            }
        )

    async def guild_info(self, request: web.Request) -> web.Response:
        await self._guard(request)
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        return _ok(
            {
                "id": str(guild.id),
                "name": guild.name,
                "member_count": guild.member_count,
                "icon_url": str(guild.icon.url) if guild.icon else None,
                "owner_id": str(guild.owner_id),
                "boost_count": guild.premium_subscription_count or 0,
                "created_at": guild.created_at.isoformat(),
            }
        )

    async def list_roles(self, request: web.Request) -> web.Response:
        await self._guard(request)
        force = request.query.get("force") == "1"
        cache_key = "roles"
        if not force:
            cached = get_cached(cache_key)
            if cached is not None:
                return _ok(cached)

        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)

        me = guild.me
        bot_top = me.top_role.position if me else 0
        roles = []
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if role.is_default():
                continue
            above_bot = role.position >= bot_top
            managed = role.managed
            roles.append(
                {
                    "id": str(role.id),
                    "name": role.name,
                    "color": f"#{role.color.value:06X}" if role.color.value else "#99AAB5",
                    "position": role.position,
                    "managed": managed,
                    "selectable": not managed and not above_bot,
                    "above_bot": above_bot,
                    "member_count": len(role.members),
                }
            )
        set_cached(cache_key, roles)
        return _ok(roles)

    async def list_channels(self, request: web.Request) -> web.Response:
        await self._guard(request)
        force = request.query.get("force") == "1"
        channel_type = request.query.get("type", "all")
        cache_key = f"channels:{channel_type}"
        if not force:
            cached = get_cached(cache_key)
            if cached is not None:
                return _ok(cached)

        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)

        channels = []
        for ch in guild.channels:
            ctype = "other"
            if isinstance(ch, discord.CategoryChannel):
                ctype = "category"
            elif isinstance(ch, discord.ForumChannel):
                ctype = "forum"
            elif isinstance(ch, discord.VoiceChannel):
                ctype = "voice"
            elif isinstance(ch, discord.StageChannel):
                ctype = "stage"
            elif isinstance(ch, discord.TextChannel):
                ctype = "text" if ch.type != discord.ChannelType.news else "announcement"

            if channel_type != "all":
                wanted = channel_type.split(",")
                if ctype not in wanted:
                    continue

            channels.append(
                {
                    "id": str(ch.id),
                    "name": ch.name,
                    "type": ctype,
                    "category_id": str(ch.category_id) if getattr(ch, "category_id", None) else None,
                    "position": ch.position,
                }
            )

        channels.sort(key=lambda c: (c["type"], c["position"], c["name"]))
        set_cached(cache_key, channels)
        return _ok(channels)

    async def invalidate_cache(self, request: web.Request) -> web.Response:
        await self._guard(request)
        invalidate()
        return _ok({"invalidated": True})

    async def publish_ticket_panel(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        channel_id = int(body.get("channel_id") or 0)
        title = body.get("title") or "Support-Center"
        description = body.get("description") or ""
        color = body.get("color") or "#9B5CFF"
        button_label = body.get("button_label") or "🎫 Ticket erstellen"
        message_id = body.get("message_id")

        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return _json_error("Ungültiger Textkanal")

        from bot.views.tickets import TicketPanelView

        embed = discord.Embed(
            title=title,
            description=description,
            color=parse_color(color),
        )
        embed.set_footer(text="zyrahd.net • Ticket-System")
        view = TicketPanelView(button_label=button_label)

        try:
            if message_id:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=embed, view=view)
                return _ok({"message_id": str(msg.id), "channel_id": str(channel.id)})
            msg = await channel.send(embed=embed, view=view)
            return _ok({"message_id": str(msg.id), "channel_id": str(channel.id)})
        except discord.HTTPException as exc:
            return _json_error(f"Discord-Fehler: {exc}")

    async def publish_verify_panel(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        channel_id = int(body.get("channel_id") or 0)
        title = body.get("title") or "Verifizierung"
        description = body.get("description") or ""
        color = body.get("color") or "#9B5CFF"
        button_label = body.get("button_label") or "✅ Verifizieren"
        message_id = body.get("message_id")

        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return _json_error("Ungültiger Textkanal")

        from bot.views.verify import VerifyView

        embed = discord.Embed(title=title, description=description, color=parse_color(color))
        view = VerifyView(button_label=button_label)
        try:
            if message_id:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=embed, view=view)
                return _ok({"message_id": str(msg.id), "channel_id": str(channel.id)})
            msg = await channel.send(embed=embed, view=view)
            return _ok({"message_id": str(msg.id), "channel_id": str(channel.id)})
        except discord.HTTPException as exc:
            return _json_error(f"Discord-Fehler: {exc}")

    async def send_embed(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        channel_id = int(body.get("channel_id") or 0)
        content = body.get("content") or None
        embed_data = body.get("embed") or {}
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return _json_error("Ungültiger Kanal")
        embed = build_embed_from_dict(embed_data) if embed_data else None
        try:
            msg = await channel.send(content=content, embed=embed)
            return _ok({"message_id": str(msg.id)})
        except discord.HTTPException as exc:
            return _json_error(str(exc))

    async def edit_embed(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        channel_id = int(body.get("channel_id") or 0)
        message_id = int(body.get("message_id") or 0)
        content = body.get("content")
        embed_data = body.get("embed") or {}
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return _json_error("Ungültiger Kanal")
        try:
            msg = await channel.fetch_message(message_id)
            embed = build_embed_from_dict(embed_data) if embed_data else None
            await msg.edit(content=content, embed=embed)
            return _ok({"message_id": str(msg.id)})
        except discord.HTTPException as exc:
            return _json_error(str(exc))

    async def assign_role(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        return await self._role_change(body, add=True)

    async def remove_role(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        return await self._role_change(body, add=False)

    async def _role_change(self, body: dict, *, add: bool) -> web.Response:
        user_id = int(body.get("user_id") or 0)
        role_id = int(body.get("role_id") or 0)
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        role = guild.get_role(role_id)
        if not member or not role:
            return _json_error("Mitglied oder Rolle nicht gefunden", 404)
        try:
            if add:
                await member.add_roles(role, reason="Dashboard")
            else:
                await member.remove_roles(role, reason="Dashboard")
            return _ok(True)
        except discord.HTTPException as exc:
            return _json_error(str(exc))

    async def moderation_action(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        action = body.get("action")
        user_id = int(body.get("user_id") or 0)
        reason = body.get("reason") or "Kein Grund angegeben"
        duration = int(body.get("duration_seconds") or 0)
        moderator_id = int(body.get("moderator_id") or 0)
        moderator_name = body.get("moderator_name") or "Dashboard"
        evidence = body.get("evidence") or ""

        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)

        member = None
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        except discord.NotFound:
            member = None

        try:
            if action == "warn":
                pass
            elif action == "timeout":
                if not member:
                    return _json_error("Mitglied nicht gefunden", 404)
                until = datetime.now(timezone.utc) + timedelta(seconds=max(duration, 60))
                await member.timeout(until, reason=reason)
            elif action == "untimeout":
                if not member:
                    return _json_error("Mitglied nicht gefunden", 404)
                await member.timeout(None, reason=reason)
            elif action == "kick":
                if not member:
                    return _json_error("Mitglied nicht gefunden", 404)
                await member.kick(reason=reason)
            elif action == "ban":
                await guild.ban(discord.Object(id=user_id), reason=reason, delete_message_days=0)
            elif action == "tempban":
                await guild.ban(discord.Object(id=user_id), reason=reason, delete_message_days=0)
            elif action == "unban":
                await guild.unban(discord.Object(id=user_id), reason=reason)
            elif action == "nickname":
                if not member:
                    return _json_error("Mitglied nicht gefunden", 404)
                await member.edit(nick=body.get("nickname") or None, reason=reason)
            else:
                return _json_error(f"Unbekannte Aktion: {action}")
        except discord.HTTPException as exc:
            return _json_error(str(exc))

        with get_session() as session:
            last = session.query(ModCase).order_by(ModCase.case_number.desc()).first()
            case_number = (last.case_number + 1) if last else 1
            expires = None
            if duration and action in {"timeout", "tempban"}:
                expires = datetime.now(timezone.utc) + timedelta(seconds=duration)
            case = ModCase(
                case_number=case_number,
                user_id=user_id,
                user_name=str(member) if member else str(user_id),
                moderator_id=moderator_id,
                moderator_name=moderator_name,
                action=action,
                reason=reason,
                evidence=evidence,
                duration_seconds=duration or None,
                expires_at=expires,
                status="active",
            )
            session.add(case)
            session.flush()
            case_id = case.id
            case_no = case.case_number

        return _ok({"case_id": case_id, "case_number": case_no})

    async def create_ticket(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        from bot.cogs.tickets import create_ticket_channel

        try:
            result = await create_ticket_channel(self.bot, body)
            return _ok(result)
        except ValueError as exc:
            return _json_error(str(exc))
        except Exception as exc:
            logger.exception("Ticket-Erstellung fehlgeschlagen")
            return _json_error(str(exc), 500)

    async def send_ticket_message(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        ticket_id = int(body.get("ticket_id") or 0)
        content = (body.get("content") or "").strip()
        author_id = int(body.get("author_id") or 0)
        author_name = body.get("author_name") or "User"
        author_avatar = body.get("author_avatar") or ""
        source = body.get("source") or "web"

        with get_session() as session:
            ticket = session.get(Ticket, ticket_id)
            if not ticket or not ticket.channel_id:
                return _json_error("Ticket nicht gefunden", 404)
            channel_id = ticket.channel_id

        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return _json_error("Ticket-Kanal nicht gefunden", 404)

        embed = discord.Embed(
            description=content,
            color=parse_color("#9B5CFF"),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=f"{author_name} (Web)", icon_url=author_avatar or None)
        try:
            msg = await channel.send(embed=embed)
        except discord.HTTPException as exc:
            return _json_error(str(exc))

        with get_session() as session:
            tm = TicketMessage(
                ticket_id=ticket_id,
                author_id=author_id,
                author_name=author_name,
                author_avatar=author_avatar,
                content=content,
                source=source,
                discord_message_id=msg.id,
            )
            session.add(tm)
            ticket = session.get(Ticket, ticket_id)
            if ticket:
                ticket.last_activity_at = datetime.now(timezone.utc)

        return _ok({"message_id": str(msg.id)})

    async def ticket_action(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        from bot.cogs.tickets import perform_ticket_action

        try:
            result = await perform_ticket_action(self.bot, body)
            return _ok(result)
        except ValueError as exc:
            return _json_error(str(exc))
        except Exception as exc:
            logger.exception("Ticket-Aktion fehlgeschlagen")
            return _json_error(str(exc), 500)

    async def publish_announcement(self, request: web.Request) -> web.Response:
        await self._guard(request)
        body = await request.json()
        channel_id = int(body.get("channel_id") or 0)
        title = body.get("title") or "Team-Ankündigung"
        message = body.get("message") or ""
        priority = body.get("priority") or "normal"
        colors = {"low": "#7E57C2", "normal": "#9B5CFF", "high": "#E040FB", "urgent": "#FF4081"}
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return _json_error("Ungültiger Kanal")
        embed = discord.Embed(
            title=f"📢 {title}",
            description=message,
            color=parse_color(colors.get(priority, "#9B5CFF")),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Priorität", value=priority.upper(), inline=True)
        try:
            msg = await channel.send(embed=embed)
            return _ok({"message_id": str(msg.id)})
        except discord.HTTPException as exc:
            return _json_error(str(exc))

    async def member_info(self, request: web.Request) -> web.Response:
        await self._guard(request)
        user_id = int(request.match_info["user_id"])
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return _json_error("Guild nicht gefunden", 404)
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        except discord.NotFound:
            return _json_error("Mitglied nicht gefunden", 404)
        return _ok(
            {
                "id": str(member.id),
                "name": member.name,
                "display_name": member.display_name,
                "avatar_url": str(member.display_avatar.url),
                "roles": [str(r.id) for r in member.roles if not r.is_default()],
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                "created_at": member.created_at.isoformat(),
            }
        )

    async def reload_settings(self, request: web.Request) -> web.Response:
        await self._guard(request)
        invalidate()
        return _ok({"reloaded": True})

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, config.INTERNAL_API_HOST, config.INTERNAL_API_PORT)
        await site.start()
        logger.info(
            "Interne API gestartet auf %s:%s",
            config.INTERNAL_API_HOST,
            config.INTERNAL_API_PORT,
        )

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()


async def start_internal_api(bot) -> InternalAPI:
    api = InternalAPI(bot)
    await api.start()
    return api
