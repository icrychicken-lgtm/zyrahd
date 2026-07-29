"""Word filter and lightweight anti-spam enforcement."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from sqlalchemy import select

from database.manager import get_setting, session_scope
from database.models import ModerationCase, WordFilter


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)


class SecurityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.recent: dict[tuple[int, int], deque[datetime]] = defaultdict(
            lambda: deque(maxlen=20)
        )

    async def _punish(
        self,
        message: discord.Message,
        *,
        action: str,
        reason: str,
        timeout_minutes: int = 10,
        response: str = "",
    ) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        if response:
            try:
                notice = await message.channel.send(
                    f"{message.author.mention} {response}",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                await notice.delete(delay=8)
            except discord.HTTPException:
                pass
        member = message.author
        try:
            if action == "timeout" and isinstance(member, discord.Member):
                await member.timeout(
                    timedelta(minutes=max(1, timeout_minutes)), reason=reason
                )
            elif action == "kick" and isinstance(member, discord.Member):
                await member.kick(reason=reason)
            elif action == "ban" and message.guild:
                await message.guild.ban(member, reason=reason, delete_message_seconds=0)
        except discord.Forbidden:
            pass
        with session_scope() as db:
            db.add(
                ModerationCase(
                    guild_id=str(message.guild.id),
                    user_id=str(member.id),
                    user_name=member.display_name,
                    moderator_id=str(self.bot.user.id if self.bot.user else 0),
                    moderator_name="zyrahd Automod",
                    action=action if action != "delete" else "automod",
                    reason=reason,
                    duration_minutes=timeout_minutes if action == "timeout" else None,
                )
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            not message.guild
            or message.author.bot
            or not isinstance(message.author, discord.Member)
            or message.author.guild_permissions.manage_messages
        ):
            return
        security = get_setting(str(message.guild.id), "security", {})
        ignored_channels = {str(item) for item in security.get("ignored_channels", [])}
        ignored_roles = {str(item) for item in security.get("ignored_roles", [])}
        if str(message.channel.id) in ignored_channels or any(
            str(role.id) in ignored_roles for role in message.author.roles
        ):
            return

        if security.get("anti_spam_enabled"):
            key = (message.guild.id, message.author.id)
            now = datetime.now(timezone.utc)
            history = self.recent[key]
            history.append(now)
            window = max(2, int(security.get("spam_window_seconds", 6)))
            while history and (now - history[0]).total_seconds() > window:
                history.popleft()
            if len(history) >= max(3, int(security.get("spam_message_limit", 6))):
                history.clear()
                await self._punish(
                    message,
                    action="timeout",
                    reason="Automod: Nachrichten-Spam",
                    timeout_minutes=max(
                        1, int(security.get("spam_timeout_minutes", 5))
                    ),
                    response="Bitte sende Nachrichten nicht so schnell hintereinander.",
                )
                return

        candidate = normalized(message.content)
        with session_scope() as db:
            filters = list(
                db.scalars(
                    select(WordFilter).where(
                        WordFilter.guild_id == str(message.guild.id),
                        WordFilter.enabled.is_(True),
                    )
                )
            )
            for item in filters:
                db.expunge(item)
        for item in filters:
            exceptions = item.exceptions
            if str(message.channel.id) in {
                str(value) for value in exceptions.get("channel_ids", [])
            } or any(
                str(role.id)
                in {str(value) for value in exceptions.get("role_ids", [])}
                for role in message.author.roles
            ):
                continue
            source = message.content if item.case_sensitive else message.content.casefold()
            phrase = item.phrase if item.case_sensitive else item.phrase.casefold()
            if item.mode == "exact":
                matched = bool(
                    re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", source)
                )
            else:
                matched = normalized(phrase) in candidate
            if matched:
                await self._punish(
                    message,
                    action=item.action,
                    reason=f"Automod-Wortfilter: {item.phrase}",
                    timeout_minutes=item.timeout_minutes,
                    response=item.response,
                )
                return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SecurityCog(bot))
