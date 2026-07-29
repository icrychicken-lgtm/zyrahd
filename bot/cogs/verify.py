"""Verify Cog – Panel-Persistenz."""

from __future__ import annotations

from discord.ext import commands

from bot.views.verify import VerifyView


class VerifyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(VerifyView())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerifyCog(bot))
