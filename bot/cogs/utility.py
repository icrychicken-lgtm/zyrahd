"""Logging und Server-Statistiken."""

from __future__ import annotations

import discord
from discord.ext import commands, tasks

import config
from bot.utils.helpers import parse_color
from database.manager import get_session
from database.models import LogConfig, ServerStatChannel, Ticket, TeamMember


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_stats.start()

    def cog_unload(self) -> None:
        self.update_stats.cancel()

    async def _log_channel(self, guild: discord.Guild, field: str) -> discord.TextChannel | None:
        with get_session() as session:
            cfg = session.query(LogConfig).first()
            if not cfg:
                return None
            channel_id = getattr(cfg, field, None)
        if not channel_id:
            return None
        ch = guild.get_channel(channel_id)
        return ch if isinstance(ch, discord.TextChannel) else None

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot or message.guild.id != config.GUILD_ID:
            return
        ch = await self._log_channel(message.guild, "message_delete")
        if not ch:
            return
        embed = discord.Embed(
            title="Nachricht gelöscht",
            description=message.content[:4000] or "*leer / Anhang*",
            color=parse_color("#E040FB"),
        )
        embed.add_field(name="Kanal", value=getattr(message.channel, "mention", "?"), inline=True)
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not before.guild or before.author.bot or before.guild.id != config.GUILD_ID:
            return
        if before.content == after.content:
            return
        ch = await self._log_channel(before.guild, "message_edit")
        if not ch:
            return
        embed = discord.Embed(title="Nachricht bearbeitet", color=parse_color("#B388FF"))
        embed.add_field(name="Vorher", value=(before.content or "—")[:1000], inline=False)
        embed.add_field(name="Nachher", value=(after.content or "—")[:1000], inline=False)
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != config.GUILD_ID:
            return
        ch = await self._log_channel(member.guild, "member_join")
        if ch:
            embed = discord.Embed(
                title="Mitglied beigetreten",
                description=f"{member.mention} (`{member.id}`)",
                color=parse_color("#9B5CFF"),
            )
            await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild.id != config.GUILD_ID:
            return
        ch = await self._log_channel(member.guild, "member_leave")
        if ch:
            embed = discord.Embed(
                title="Mitglied verlassen",
                description=f"{member} (`{member.id}`)",
                color=parse_color("#6B4C9A"),
            )
            await ch.send(embed=embed)

    @tasks.loop(minutes=5)
    async def update_stats(self) -> None:
        if not self.bot.is_ready():
            return
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return

        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        with get_session() as session:
            open_tickets = session.query(Ticket).filter(Ticket.status.in_(["open", "claimed", "waiting"])).count()
            team_count = session.query(TeamMember).filter(TeamMember.status == "active").count()
            rows = session.query(ServerStatChannel).filter(ServerStatChannel.enabled.is_(True)).all()
            stats = {
                "members": guild.member_count or 0,
                "humans": humans,
                "bots": bots,
                "boosts": guild.premium_subscription_count or 0,
                "online": online,
                "tickets": open_tickets,
                "team": team_count,
            }
            for row in rows:
                if not row.channel_id:
                    continue
                value = stats.get(row.stat_type)
                if value is None:
                    continue
                channel = guild.get_channel(row.channel_id)
                if not channel:
                    continue
                name = row.name_format.replace("{name}", row.stat_type.title()).replace("{value}", str(value))
                try:
                    await channel.edit(name=name[:100])
                except discord.HTTPException:
                    pass

    @update_stats.before_loop
    async def before_stats(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
