"""Automod- und Sicherheitssystem."""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

import config
from bot.utils.audit import write_activity
from bot.utils.helpers import contains_invite, contains_url, normalize_text_for_filter, parse_color
from database.manager import get_session
from database.models import SecurityConfig, SecurityEvent, UserStrike, WordFilter


class SecurityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.msg_buckets: dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
        self.dup_buckets: dict[int, deque] = defaultdict(lambda: deque(maxlen=5))
        self.join_times: deque = deque(maxlen=100)

    def _get_config(self) -> SecurityConfig | None:
        with get_session() as session:
            cfg = session.query(SecurityConfig).first()
            if not cfg:
                return None
            session.expunge(cfg)
            return cfg

    def _exempt(self, member: discord.Member, cfg: SecurityConfig, channel_id: int) -> bool:
        if member.guild_permissions.administrator:
            return True
        if member.id in cfg.get_whitelist_users():
            return True
        if channel_id in cfg.get_exempt_channels():
            return True
        member_roles = {r.id for r in member.roles}
        if member_roles & set(cfg.get_exempt_roles()):
            return True
        return False

    async def _log(self, guild: discord.Guild, cfg: SecurityConfig, title: str, desc: str, user: discord.Member | None = None):
        with get_session() as session:
            session.add(
                SecurityEvent(
                    event_type=title,
                    user_id=user.id if user else None,
                    username=str(user) if user else "",
                    details=desc,
                    action_taken=title,
                )
            )
        if cfg.log_channel_id:
            ch = guild.get_channel(cfg.log_channel_id)
            if isinstance(ch, discord.TextChannel):
                embed = discord.Embed(title=title, description=desc, color=parse_color("#E040FB"), timestamp=datetime.now(timezone.utc))
                if user:
                    embed.set_author(name=str(user), icon_url=user.display_avatar.url)
                await ch.send(embed=embed)

    async def _punish(self, message: discord.Message, cfg: SecurityConfig, reason: str, *, timeout: int = 0, delete: bool = True):
        if delete:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        if timeout > 0:
            try:
                until = datetime.now(timezone.utc) + timedelta(seconds=timeout)
                await message.author.timeout(until, reason=reason)
            except discord.HTTPException:
                pass
        try:
            await message.channel.send(
                f"⚠️ {message.author.mention}: {reason}",
                delete_after=8,
            )
        except discord.HTTPException:
            pass
        await self._log(message.guild, cfg, "Automod", reason, message.author)
        write_activity("security", f"{message.author}: {reason}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != config.GUILD_ID:
            return
        cfg = self._get_config()
        if not cfg:
            return

        now = time.time()
        self.join_times.append(now)

        if cfg.min_account_age_days > 0:
            created = member.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - created).days
            if age < cfg.min_account_age_days:
                try:
                    await member.kick(reason=f"Account zu jung ({age} Tage)")
                    await self._log(member.guild, cfg, "Anti-Bot/Alter", f"{member} gekickt (Account {age} Tage)", member)
                except discord.HTTPException:
                    pass
                return

        if cfg.anti_bot_join and member.bot:
            try:
                await member.kick(reason="Anti-Bot-Join")
                await self._log(member.guild, cfg, "Anti-Bot-Join", f"Bot {member} gekickt", member)
            except discord.HTTPException:
                pass
            return

        if cfg.anti_raid or cfg.emergency_mode:
            window = cfg.raid_join_window_seconds or 10
            recent = [t for t in self.join_times if now - t <= window]
            if cfg.emergency_mode or len(recent) >= (cfg.raid_join_threshold or 8):
                try:
                    until = datetime.now(timezone.utc) + timedelta(seconds=cfg.raid_timeout_seconds or 600)
                    await member.timeout(until, reason="Anti-Raid")
                except discord.HTTPException:
                    pass
                await self._log(member.guild, cfg, "Anti-Raid", f"Raid-Schutz: {member} getimeoutet", member)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        if message.guild.id != config.GUILD_ID:
            return
        if not isinstance(message.author, discord.Member):
            return

        cfg = self._get_config()
        if not cfg:
            return
        if self._exempt(message.author, cfg, message.channel.id):
            return

        content = message.content or ""
        now = time.time()

        # Emergency
        if cfg.emergency_mode:
            await self._punish(message, cfg, "Notfallmodus aktiv – Nachrichten eingeschränkt.", delete=True)
            return

        # Anti-spam
        if cfg.anti_spam:
            bucket = self.msg_buckets[message.author.id]
            bucket.append(now)
            window = cfg.spam_seconds or 5
            limit = cfg.spam_messages or 5
            recent = [t for t in bucket if now - t <= window]
            if len(recent) >= limit:
                await self._punish(message, cfg, "Anti-Spam ausgelöst.", timeout=300)
                return

        # Duplicate
        if cfg.anti_duplicate and content:
            dbucket = self.dup_buckets[message.author.id]
            dbucket.append(content.lower().strip())
            if len(dbucket) >= 3 and len(set(dbucket)) == 1:
                await self._punish(message, cfg, "Doppelte Nachrichten erkannt.", timeout=120)
                return

        # Invites
        if cfg.anti_invite and contains_invite(content):
            await self._punish(message, cfg, "Discord-Einladungen sind nicht erlaubt.")
            return

        # Links
        if cfg.anti_link and contains_url(content):
            allowed = False
            for domain in cfg.get_link_whitelist():
                if domain.lower() in content.lower():
                    allowed = True
                    break
            if not allowed:
                await self._punish(message, cfg, "Links sind nicht erlaubt.")
                return

        # Mentions
        if cfg.anti_mention_spam and len(message.mentions) + len(message.role_mentions) >= (cfg.mention_limit or 5):
            await self._punish(message, cfg, "Zu viele Mentions.", timeout=300)
            return

        # Caps
        if cfg.anti_caps and len(content) >= 12:
            letters = [c for c in content if c.isalpha()]
            if letters:
                caps = sum(1 for c in letters if c.isupper())
                if (caps / len(letters)) * 100 >= (cfg.caps_percent or 70):
                    await self._punish(message, cfg, "Bitte weniger Caps.")
                    return

        # Zalgo
        if cfg.anti_zalgo and len(re.findall(r"[\u0300-\u036f]", content)) > 8:
            await self._punish(message, cfg, "Zalgo-Text ist nicht erlaubt.")
            return

        # Mass emoji
        if cfg.anti_mass_emoji:
            emoji_count = len(re.findall(r"<a?:\w+:\d+>", content)) + len(re.findall(r"[\U0001F300-\U0001FAFF]", content))
            if emoji_count >= (cfg.emoji_limit or 10):
                await self._punish(message, cfg, "Zu viele Emojis.")
                return

        # Word filter
        await self._check_word_filters(message, cfg)

    async def _check_word_filters(self, message: discord.Message, cfg: SecurityConfig) -> None:
        content = message.content or ""
        normalized = normalize_text_for_filter(content)

        with get_session() as session:
            filters = session.query(WordFilter).filter(WordFilter.enabled.is_(True)).all()
            for wf in filters:
                if message.channel.id in wf.get_allowed_channels():
                    continue
                member_roles = {r.id for r in message.author.roles}
                if member_roles & set(wf.get_exempt_roles()):
                    continue

                pattern = wf.pattern
                hay = content if wf.case_sensitive else content.lower()
                needle = pattern if wf.case_sensitive else pattern.lower()
                matched = False
                if wf.match_type == "exact":
                    matched = hay.strip() == needle or normalized == normalize_text_for_filter(pattern)
                else:
                    matched = needle in hay or normalize_text_for_filter(pattern) in normalized

                if not matched:
                    continue

                # Strikes
                strike = (
                    session.query(UserStrike)
                    .filter(UserStrike.user_id == message.author.id, UserStrike.filter_id == wf.id)
                    .first()
                )
                if strike:
                    strike.count += 1
                    count = strike.count
                else:
                    strike = UserStrike(user_id=message.author.id, filter_id=wf.id, reason=pattern, count=1)
                    session.add(strike)
                    count = 1

                if count < (wf.strikes_needed or 1):
                    if wf.delete_message:
                        try:
                            await message.delete()
                        except discord.HTTPException:
                            pass
                    if wf.response_message:
                        try:
                            await message.channel.send(wf.response_message, delete_after=8)
                        except discord.HTTPException:
                            pass
                    return

                if wf.delete_message:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass

                reason = wf.response_message or f"Wortfilter: `{wf.pattern}`"
                if wf.warn_user:
                    try:
                        await message.author.send(f"Verwarnung auf {message.guild.name}: {reason}")
                    except discord.HTTPException:
                        pass
                if wf.timeout_seconds:
                    try:
                        until = datetime.now(timezone.utc) + timedelta(seconds=wf.timeout_seconds)
                        await message.author.timeout(until, reason=reason)
                    except discord.HTTPException:
                        pass
                if wf.kick:
                    try:
                        await message.author.kick(reason=reason)
                    except discord.HTTPException:
                        pass
                if wf.ban:
                    try:
                        await message.author.ban(reason=reason)
                    except discord.HTTPException:
                        pass

                await self._log(message.guild, cfg, "Wortfilter", reason, message.author)
                return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SecurityCog(bot))
