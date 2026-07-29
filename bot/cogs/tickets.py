"""Slash command entry points for ticket panels and controls."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class TicketCog(commands.Cog):
    ticket = app_commands.Group(name="ticket", description="Ticket-Verwaltung")

    def __init__(self, bot):
        self.bot = bot

    @ticket.command(name="panel", description="Veröffentlicht das Ticket-Panel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.bot.service.publish_ticket_panel(channel.id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"Panel veröffentlicht: {result['message_id']}", ephemeral=True
        )

    @ticket.command(name="close", description="Schließt das aktuelle Ticket.")
    async def close(
        self, interaction: discord.Interaction, reason: str = "Per Befehl geschlossen"
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.service.close_ticket_by_channel(
                interaction.channel_id, interaction.user.id, reason
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("Ticket geschlossen.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(TicketCog(bot))
