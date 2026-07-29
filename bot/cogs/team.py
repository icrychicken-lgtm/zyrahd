"""Team-Ankündigungen und Aktivitäts-Tracking."""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import config
from database.manager import get_session
from database.models import TeamAnnouncement
from bot.utils.helpers import parse_color


class TeamCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.publish_scheduled.start()

    def cog_unload(self) -> None:
        self.publish_scheduled.cancel()

    @tasks.loop(minutes=1)
    async def publish_scheduled(self) -> None:
        if not self.bot.is_ready():
            return
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return
        now = datetime.now(timezone.utc)
        with get_session() as session:
            pending = (
                session.query(TeamAnnouncement)
                .filter(TeamAnnouncement.published.is_(False))
                .filter(TeamAnnouncement.publish_at.isnot(None))
                .filter(TeamAnnouncement.publish_at <= now)
                .all()
            )
            for ann in pending:
                if not ann.channel_id:
                    continue
                channel = guild.get_channel(ann.channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
                colors = {"low": "#7E57C2", "normal": "#9B5CFF", "high": "#E040FB", "urgent": "#FF4081"}
                embed = discord.Embed(
                    title=f"📢 {ann.title}",
                    description=ann.message,
                    color=parse_color(colors.get(ann.priority, "#9B5CFF")),
                    timestamp=now,
                )
                try:
                    msg = await channel.send(embed=embed)
                    ann.message_id = msg.id
                    ann.published = True
                except discord.HTTPException:
                    pass

    @publish_scheduled.before_loop
    async def before_publish(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TeamCog(bot))
