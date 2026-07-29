"""Ticket slash command and Discord-to-dashboard message mirror."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.views.ticket_panel import TicketPanelView
from database.manager import session_scope
from database.models import Ticket, TicketMessage


class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ticket", description="Öffnet das Ticket-Center")
    async def ticket(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Wähle **Ticket erstellen**, um den passenden Bereich auszuwählen.",
            view=TicketPanelView(),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            message.author.bot
            or not message.guild
            or not isinstance(message.channel, discord.TextChannel)
        ):
            return
        with session_scope() as db:
            ticket = db.scalar(
                select(Ticket).where(
                    Ticket.discord_channel_id == str(message.channel.id)
                )
            )
            if not ticket:
                return
            attachments = [
                {
                    "name": attachment.filename,
                    "url": attachment.url,
                    "content_type": attachment.content_type,
                    "size": attachment.size,
                }
                for attachment in message.attachments
            ]
            row = TicketMessage(
                ticket_id=ticket.id,
                author_id=str(message.author.id),
                author_name=message.author.display_name,
                author_avatar=message.author.display_avatar.url,
                content=message.content or ("📎 Anhang" if attachments else ""),
                source="discord",
                discord_message_id=str(message.id),
            )
            row.attachments = attachments
            db.add(row)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
