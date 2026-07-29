"""Vorschlags-System."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from bot.utils.helpers import parse_color
from database.manager import get_session
from database.models import Setting, Suggestion


class SuggestionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="👍", style=discord.ButtonStyle.success, custom_id="zyrahd:sug:up")
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._vote(interaction, 1)

    @discord.ui.button(label="👎", style=discord.ButtonStyle.danger, custom_id="zyrahd:sug:down")
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._vote(interaction, -1)

    async def _vote(self, interaction: discord.Interaction, delta: int) -> None:
        with get_session() as session:
            sug = session.query(Suggestion).filter(Suggestion.message_id == interaction.message.id).first()
            if not sug or sug.status != "open":
                await interaction.response.send_message("Vorschlag nicht abstimmbar.", ephemeral=True)
                return
            if delta > 0:
                sug.upvotes += 1
            else:
                sug.downvotes += 1
            up, down = sug.upvotes, sug.downvotes
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        # Update vote fields
        embed.clear_fields()
        embed.add_field(name="👍", value=str(up), inline=True)
        embed.add_field(name="👎", value=str(down), inline=True)
        await interaction.response.edit_message(embed=embed)


class SuggestionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(SuggestionView())

    @app_commands.command(name="suggest", description="Vorschlag einreichen")
    async def suggest(self, interaction: discord.Interaction, text: str):
        with get_session() as session:
            setting = session.query(Setting).filter(Setting.key == "suggestions_channel_id").first()
            channel_id = int(setting.value) if setting and setting.value.isdigit() else None
            last = session.query(Suggestion).order_by(Suggestion.number.desc()).first()
            number = (last.number + 1) if last else 1

        channel = None
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            channel = interaction.channel

        embed = discord.Embed(
            title=f"💡 Vorschlag #{number}",
            description=text,
            color=parse_color("#9B5CFF"),
        )
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="👍", value="0", inline=True)
        embed.add_field(name="👎", value="0", inline=True)
        view = SuggestionView()
        msg = await channel.send(embed=embed, view=view)
        try:
            await msg.create_thread(name=f"Vorschlag-{number}")
            thread_id = msg.id  # thread created from message
        except discord.HTTPException:
            thread_id = None

        with get_session() as session:
            session.add(
                Suggestion(
                    number=number,
                    author_id=interaction.user.id,
                    author_name=str(interaction.user),
                    content=text,
                    channel_id=channel.id,
                    message_id=msg.id,
                    thread_id=thread_id,
                )
            )
        await interaction.response.send_message(f"Vorschlag #{number} eingereicht.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SuggestionsCog(bot))
