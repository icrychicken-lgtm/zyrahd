"""Giveaway-System."""

from __future__ import annotations

import random
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from bot.utils.helpers import parse_color
from database.manager import get_session
from database.models import Giveaway, _json_dumps, _json_loads


class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id: int):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(label="🎉 Teilnehmen", style=discord.ButtonStyle.primary, custom_id="zyrahd:giveaway:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        with get_session() as session:
            g = (
                session.query(Giveaway)
                .filter(Giveaway.message_id == interaction.message.id)
                .first()
            )
            if not g or g.status != "active":
                await interaction.response.send_message("Giveaway nicht aktiv.", ephemeral=True)
                return
            entrants = _json_loads(g.entrants, default=[])
            uid = interaction.user.id
            if uid in entrants:
                entrants = [e for e in entrants if e != uid]
                g.entrants = _json_dumps(entrants)
                await interaction.response.send_message("Teilnahme zurückgezogen.", ephemeral=True)
            else:
                entrants.append(uid)
                g.entrants = _json_dumps(entrants)
                await interaction.response.send_message("Du nimmst teil! 🎉", ephemeral=True)


class GiveawaysCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()
        bot.add_view(GiveawayView(0))

    def cog_unload(self) -> None:
        self.check_giveaways.cancel()

    @tasks.loop(minutes=1)
    async def check_giveaways(self) -> None:
        if not self.bot.is_ready():
            return
        now = datetime.now(timezone.utc)
        with get_session() as session:
            active = (
                session.query(Giveaway)
                .filter(Giveaway.status == "active", Giveaway.ends_at <= now)
                .all()
            )
            for g in list(active):
                await self._end_giveaway(session, g)

    async def _end_giveaway(self, session, g: Giveaway) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return
        entrants = _json_loads(g.entrants, default=[])
        winners = []
        if entrants:
            k = min(g.winners_count, len(entrants))
            winners = random.sample(entrants, k)
        g.winner_ids = _json_dumps(winners)
        g.status = "ended"
        channel = guild.get_channel(g.channel_id) if g.channel_id else None
        if isinstance(channel, discord.TextChannel) and g.message_id:
            try:
                msg = await channel.fetch_message(g.message_id)
                mention = ", ".join(f"<@{w}>" for w in winners) or "Keine Teilnehmer"
                embed = msg.embeds[0] if msg.embeds else discord.Embed(title="Giveaway")
                embed.description = f"**Preis:** {g.prize}\n**Gewinner:** {mention}"
                embed.color = parse_color("#6B4C9A")
                await msg.edit(embed=embed, view=None)
                await channel.send(f"🎉 Giveaway beendet! Gewinner: {mention}")
            except discord.HTTPException:
                pass

    @check_giveaways.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="giveaway", description="Giveaway erstellen")
    @app_commands.default_permissions(manage_guild=True)
    async def giveaway_cmd(
        self,
        interaction: discord.Interaction,
        prize: str,
        minutes: app_commands.Range[int, 1, 10080],
        winners: app_commands.Range[int, 1, 20] = 1,
    ):
        ends = datetime.now(timezone.utc).timestamp() + minutes * 60
        ends_dt = datetime.fromtimestamp(ends, tz=timezone.utc)
        embed = discord.Embed(
            title="🎉 Giveaway",
            description=f"**Preis:** {prize}\n**Gewinner:** {winners}\nEndet: <t:{int(ends)}:R>",
            color=parse_color("#9B5CFF"),
        )
        with get_session() as session:
            g = Giveaway(
                prize=prize,
                channel_id=interaction.channel_id,
                winners_count=winners,
                ends_at=ends_dt,
                created_by=interaction.user.id,
            )
            session.add(g)
            session.flush()
            gid = g.id
        view = GiveawayView(gid)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        with get_session() as session:
            g = session.get(Giveaway, gid)
            if g:
                g.message_id = msg.id


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GiveawaysCog(bot))
