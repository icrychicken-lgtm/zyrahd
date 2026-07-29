"""Confirmation control for internal team announcements."""

from __future__ import annotations

import discord
from sqlalchemy import select

from database.manager import session_scope
from database.models import JsonMixin, TeamAnnouncement


class AnnouncementConfirmView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Gelesen & bestätigt",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="zyrahd:announcement:confirm",
    )
    async def confirm(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        with session_scope() as db:
            row = db.scalar(
                select(TeamAnnouncement).where(
                    TeamAnnouncement.discord_message_id == str(interaction.message.id)
                )
            )
            if not row or not row.require_confirmation:
                await interaction.response.send_message(
                    "Diese Ankündigung benötigt keine Bestätigung.", ephemeral=True
                )
                return
            confirmed = JsonMixin.decode(row.confirmed_user_ids_json, [])
            if str(interaction.user.id) in confirmed:
                await interaction.response.send_message(
                    "Du hast diese Ankündigung bereits bestätigt.", ephemeral=True
                )
                return
            confirmed.append(str(interaction.user.id))
            row.confirmed_user_ids_json = JsonMixin.encode(confirmed)
        await interaction.response.send_message(
            "Danke, deine Bestätigung wurde gespeichert.", ephemeral=True
        )
