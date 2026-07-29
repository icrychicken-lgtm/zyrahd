"""Discord client lifecycle and event wiring."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

from bot.services import BotService
from bot.views import (
    AnnouncementConfirmView,
    TicketControlView,
    TicketPanelView,
    VerifyView,
)
from config import settings
from database.models import TeamAnnouncement, db

logger = logging.getLogger(__name__)
EXTENSIONS = ("bot.cogs.tickets", "bot.cogs.moderation")


class ZyrahdBot(commands.Bot):
    def __init__(self, web_app: Flask):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True
            ),
        )
        self.web_app = web_app
        self.service = BotService(self, web_app)
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self._ready_logged = False

    async def setup_hook(self) -> None:
        self.event_loop = asyncio.get_running_loop()
        loaded = []
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
            except Exception:
                logger.exception("Modul konnte nicht geladen werden: %s", extension)
                raise
            loaded.append(extension)
            logger.info("Modul geladen: %s", extension)

        self.add_view(TicketPanelView(self.service))
        self.add_view(TicketControlView(self.service))
        self.add_view(VerifyView(self.service))
        with self.web_app.app_context():
            announcements = db.session.scalars(
                db.select(TeamAnnouncement).where(
                    TeamAnnouncement.require_confirmation.is_(True),
                    TeamAnnouncement.published_message_id.is_not(None),
                )
            ).all()
            for announcement in announcements:
                self.add_view(
                    AnnouncementConfirmView(self.service, announcement.id),
                    message_id=int(announcement.published_message_id),
                )

        guild = discord.Object(id=settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info(
            "%d Slash-Commands mit Server %s synchronisiert.",
            len(synced),
            settings.guild_id,
        )
        logger.info("%d Module erfolgreich geladen.", len(loaded))

    async def on_ready(self) -> None:
        if self._ready_logged:
            return
        self._ready_logged = True
        guild = self.get_guild(settings.guild_id)
        logger.info("Discord-Anmeldung erfolgreich als %s.", self.user)
        if guild:
            logger.info("Server geladen: %s (%s).", guild.name, guild.id)
        else:
            logger.error(
                "GUILD_ID %s wurde nicht gefunden. Ist der Bot auf dem Server?",
                settings.guild_id,
            )

    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id == settings.guild_id:
            await self.service.welcome_member(member)

    async def on_message(self, message: discord.Message) -> None:
        if message.guild and message.guild.id == settings.guild_id:
            blocked = await self.service.enforce_security(message)
            if not blocked:
                await self.service.mirror_discord_message(message)
        await self.process_commands(message)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        logger.error("Slash-Command fehlgeschlagen: %s", error)
        message = "Der Befehl konnte nicht ausgeführt werden."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
