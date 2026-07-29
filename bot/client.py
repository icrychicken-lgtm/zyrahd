"""Discord-Bot Einstiegspunkt und Lifecycle."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Optional

import discord
from discord.ext import commands

import config
from database.manager import init_db

logger = logging.getLogger("zyrahd.bot")

COGS = [
    "bot.cogs.moderation",
    "bot.cogs.tickets",
    "bot.cogs.welcome",
    "bot.cogs.verify",
    "bot.cogs.security",
    "bot.cogs.embeds",
    "bot.cogs.team",
    "bot.cogs.utility",
    "bot.cogs.giveaways",
    "bot.cogs.suggestions",
    "bot.cogs.tempvoice",
    "bot.cogs.serverstatus",
]


class ZyrahdBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.moderation = True
        intents.voice_states = True
        intents.reactions = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.guild_id = config.GUILD_ID
        self._synced = False
        self.loaded_modules: list[str] = []
        self.internal_api = None

    async def setup_hook(self) -> None:
        init_db()
        for cog in COGS:
            try:
                await self.load_extension(cog)
                self.loaded_modules.append(cog.split(".")[-1])
                logger.info("Modul geladen: %s", cog)
            except Exception as exc:
                logger.error("Modul %s konnte nicht geladen werden: %s", cog, exc)
                logger.debug(traceback.format_exc())

        # Persistente Views
        from bot.views.tickets import TicketPanelView
        from bot.views.verify import VerifyView

        self.add_view(TicketPanelView())
        self.add_view(VerifyView())

        # Interne API im Bot-Prozess starten
        from bot.internal_api import start_internal_api

        self.internal_api = await start_internal_api(self)

    async def on_ready(self) -> None:
        guild = self.get_guild(self.guild_id) if self.guild_id else None
        if guild:
            logger.info("Angemeldet als %s (ID: %s)", self.user, self.user.id if self.user else "?")
            logger.info("Server geladen: %s (ID: %s)", guild.name, guild.id)
        else:
            logger.warning(
                "Angemeldet als %s – Guild %s nicht gefunden. Prüfe GUILD_ID und Bot-Einladung.",
                self.user,
                self.guild_id,
            )

        if not self._synced:
            try:
                if self.guild_id:
                    guild_obj = discord.Object(id=self.guild_id)
                    self.tree.copy_global_to(guild=guild_obj)
                    synced = await self.tree.sync(guild=guild_obj)
                else:
                    synced = await self.tree.sync()
                self._synced = True
                logger.info("%s Slash-Command(s) synchronisiert", len(synced))
            except Exception as exc:
                logger.error("Slash-Command-Sync fehlgeschlagen: %s", exc)
                logger.debug(traceback.format_exc())

        logger.info("Geladene Module: %s", ", ".join(self.loaded_modules) or "keine")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="zyrahd.net",
            )
        )

    def get_main_guild(self) -> Optional[discord.Guild]:
        if not self.guild_id:
            return None
        return self.get_guild(self.guild_id)


async def create_bot() -> ZyrahdBot:
    return ZyrahdBot()


def run_bot() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    missing = config.validate_runtime_config(require_bot=True, require_oauth=False)
    if missing:
        raise SystemExit(
            "Fehlende .env-Variablen für den Bot: " + ", ".join(missing)
        )
    bot = ZyrahdBot()
    bot.run(config.DISCORD_BOT_TOKEN, log_handler=None)
