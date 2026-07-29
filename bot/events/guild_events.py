"""Welcome messages, ticket mirroring and configurable message protection."""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from string import Template

import discord
from discord.ext import commands
from sqlalchemy import select

from database.manager import get_setting, session_scope
from database.models import Ticket, TicketMessage, WordFilter


def _render(text: str, member: discord.Member) -> str:
    values = {
        "user": str(member),
        "username": member.name,
        "display_name": member.display_name,
        "mention": member.mention,
        "server": member.guild.name,
        "member_count": str(member.guild.member_count or 0),
        "created_at": discord.utils.format_dt(member.created_at, "D"),
        "joined_at": discord.utils.format_dt(member.joined_at or datetime.now(UTC), "D"),
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _normalized(value: str) -> str:
    substitutions = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s"})
    return re.sub(r"[^a-zäöüß]", "", value.lower().translate(substitutions))


class GuildEvents(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.message_windows: dict[int, deque[datetime]] = defaultdict(
            lambda: deque(maxlen=20)
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        with session_scope() as session:
            config = get_setting(session, str(member.guild.id), "welcome", {})
        if not config.get("enabled"):
            return
        role_ids = config.get("role_ids", [])
        roles = [
            role
            for role_id in role_ids
            if (role := member.guild.get_role(int(role_id)))
            and not role.managed
            and role < member.guild.me.top_role
        ]
        if roles:
            try:
                await member.add_roles(*roles, reason="Automatische Willkommensrollen")
            except discord.HTTPException:
                pass
        channel_id = str(config.get("channel_id") or "")
        channel = (
            member.guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
        )
        if isinstance(channel, discord.TextChannel):
            description = _render(
                config.get(
                    "description",
                    "Willkommen {mention} auf **{server}**! Du bist Mitglied #{member_count}.",
                ),
                member,
            )
            if config.get("mode", "embed") == "text":
                await channel.send(description)
            else:
                try:
                    color = discord.Color.from_str(config.get("color", "#8b5cf6"))
                except ValueError:
                    color = discord.Color.purple()
                embed = discord.Embed(
                    title=_render(config.get("title", "Willkommen!"), member),
                    description=description,
                    color=color,
                    timestamp=datetime.now(UTC),
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                if config.get("footer"):
                    embed.set_footer(text=_render(config["footer"], member))
                await channel.send(embed=embed)
        if config.get("dm_message"):
            try:
                await member.send(_render(config["dm_message"], member))
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        with session_scope() as session:
            config = get_setting(session, str(member.guild.id), "farewell", {})
        channel_id = str(config.get("channel_id") or "")
        channel = (
            member.guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
        )
        if config.get("enabled") and isinstance(channel, discord.TextChannel):
            await channel.send(
                _render(
                    config.get(
                        "message", "**{display_name}** hat {server} verlassen."
                    ),
                    member,
                )
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        await self._mirror_ticket_message(message)
        await self._apply_protection(message)

    async def _mirror_ticket_message(self, message: discord.Message) -> None:
        with session_scope() as session:
            ticket = session.scalar(
                select(Ticket).where(Ticket.channel_id == str(message.channel.id))
            )
            if not ticket:
                return
            session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=str(message.author.id),
                    author_name=message.author.display_name,
                    author_avatar=message.author.display_avatar.url,
                    content=message.content or "(Anhang)",
                    source="discord",
                    attachment_url=message.attachments[0].url
                    if message.attachments
                    else None,
                    message_id=str(message.id),
                )
            )

    async def _apply_protection(self, message: discord.Message) -> None:
        if message.author.guild_permissions.manage_messages:
            return
        with session_scope() as session:
            security = get_setting(session, str(message.guild.id), "security", {})
            filters = list(
                session.scalars(
                    select(WordFilter).where(
                        WordFilter.guild_id == str(message.guild.id),
                        WordFilter.enabled.is_(True),
                    )
                )
            )
        ignored_channels = {str(item) for item in security.get("ignored_channel_ids", [])}
        ignored_roles = {str(item) for item in security.get("ignored_role_ids", [])}
        if str(message.channel.id) in ignored_channels or any(
            str(role.id) in ignored_roles for role in message.author.roles
        ):
            return

        content = message.content
        normalized_content = _normalized(content)
        for item in filters:
            phrase = item.phrase if item.case_sensitive else item.phrase.lower()
            candidate = content if item.case_sensitive else content.lower()
            if item.match_type == "exact":
                matched = bool(
                    re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", candidate)
                )
            else:
                matched = phrase in candidate
                if not matched and len(_normalized(phrase)) >= 4:
                    matched = _normalized(phrase) in normalized_content
            if matched:
                await self._punish(message, item.action, item.timeout_minutes, item.response)
                return

        if security.get("anti_spam_enabled"):
            now = datetime.now(UTC)
            window = self.message_windows[message.author.id]
            window.append(now)
            seconds = max(2, int(security.get("spam_window_seconds", 6)))
            while window and window[0] < now - timedelta(seconds=seconds):
                window.popleft()
            if len(window) >= max(3, int(security.get("spam_message_limit", 6))):
                window.clear()
                await self._punish(
                    message,
                    security.get("spam_action", "delete"),
                    int(security.get("spam_timeout_minutes", 5)),
                    "Bitte sende Nachrichten etwas langsamer.",
                )

    async def _punish(
        self, message: discord.Message, action: str, timeout_minutes: int, response: str
    ) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            if action == "timeout":
                await message.author.timeout(
                    timedelta(minutes=max(1, timeout_minutes)),
                    reason="Zyrahd Sicherheitsfilter",
                )
            elif action == "kick":
                await message.author.kick(reason="Zyrahd Sicherheitsfilter")
            elif action == "ban":
                await message.author.ban(reason="Zyrahd Sicherheitsfilter")
            elif action == "warn":
                await message.author.send(
                    f"Deine Nachricht auf **{message.guild.name}** wurde blockiert."
                )
        except discord.HTTPException:
            pass
        if response and action not in {"kick", "ban"}:
            try:
                await message.channel.send(
                    f"{message.author.mention} {response}", delete_after=8
                )
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuildEvents(bot))
