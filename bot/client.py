"""Discord client lifecycle and one-time slash-command synchronization."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from config import settings

log = logging.getLogger("zyrahd.bot")


class ZyrahdBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.moderation = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=True, users=True, replied_user=False
            ),
        )
        self.synced = False
        self.main_loop: asyncio.AbstractEventLoop | None = None

    async def setup_hook(self) -> None:
        self.main_loop = asyncio.get_running_loop()
        modules = (
            "bot.cogs.tickets",
            "bot.cogs.moderation",
            "bot.cogs.utility",
            "bot.events.guild_events",
        )
        for module in modules:
            try:
                await self.load_extension(module)
                log.info("Modul geladen: %s", module)
            except Exception:
                log.exception("Modul konnte nicht geladen werden: %s", module)

        from bot.cogs.tickets import TicketControls

        self.add_view(TicketControls())

        if settings.guild_id:
            guild = discord.Object(id=settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                commands_synced = await self.tree.sync(guild=guild)
                self.synced = True
                log.info(
                    "%d Slash-Commands mit Server %s synchronisiert.",
                    len(commands_synced),
                    settings.guild_id,
                )
            except discord.HTTPException:
                log.exception("Slash-Commands konnten nicht synchronisiert werden.")

    async def on_ready(self) -> None:
        guild = self.get_guild(settings.guild_id) if settings.guild_id else None
        if guild:
            log.info(
                "Discord-Anmeldung erfolgreich: %s | Server: %s (%s)",
                self.user,
                guild.name,
                guild.id,
            )
        else:
            log.warning(
                "Discord-Anmeldung erfolgreich (%s), Zielserver wurde aber nicht gefunden.",
                self.user,
            )

    async def close(self) -> None:
        log.info("Discord-Verbindung wird beendet.")
        await super().close()
