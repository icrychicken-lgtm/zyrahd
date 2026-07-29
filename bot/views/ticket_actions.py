"""Persistent Discord controls shown inside ticket channels."""

from __future__ import annotations

from datetime import datetime, timezone

import discord

from database.manager import session_scope
from database.models import Ticket


class TicketActionsView(discord.ui.View):
    def __init__(self, ticket_id: int | None = None) -> None:
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    def _id_from_channel(self, interaction: discord.Interaction) -> int | None:
        if self.ticket_id:
            return self.ticket_id
        if interaction.channel and interaction.channel.topic:
            marker = "zyrahd Ticket #"
            if marker in interaction.channel.topic:
                raw = interaction.channel.topic.split(marker, 1)[1].split(" ", 1)[0]
                return int(raw) if raw.isdigit() else None
        return None

    @discord.ui.button(
        label="Übernehmen",
        emoji="🙋",
        style=discord.ButtonStyle.primary,
        custom_id="zyrahd:ticket:claim",
    )
    async def claim(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "Dafür fehlt dir die Berechtigung Nachrichten verwalten.", ephemeral=True
            )
            return
        ticket_id = self._id_from_channel(interaction)
        with session_scope() as db:
            ticket = db.get(Ticket, ticket_id) if ticket_id else None
            if not ticket or ticket.status not in ("open", "waiting"):
                await interaction.response.send_message(
                    "Dieses Ticket kann nicht übernommen werden.", ephemeral=True
                )
                return
            ticket.status = "claimed"
            ticket.assigned_to_id = str(interaction.user.id)
            ticket.assigned_to_name = interaction.user.display_name
            ticket.updated_at = datetime.now(timezone.utc)
        await interaction.response.send_message(
            f"🙋 {interaction.user.mention} hat das Ticket übernommen."
        )

    @discord.ui.button(
        label="Warten",
        emoji="⏳",
        style=discord.ButtonStyle.secondary,
        custom_id="zyrahd:ticket:wait",
    )
    async def waiting(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "Dafür fehlt dir die Berechtigung Nachrichten verwalten.", ephemeral=True
            )
            return
        ticket_id = self._id_from_channel(interaction)
        with session_scope() as db:
            ticket = db.get(Ticket, ticket_id) if ticket_id else None
            if not ticket or ticket.status not in ("open", "claimed"):
                await interaction.response.send_message(
                    "Der Status kann nicht geändert werden.", ephemeral=True
                )
                return
            ticket.status = "waiting"
            ticket.updated_at = datetime.now(timezone.utc)
        await interaction.response.send_message("⏳ Das Ticket wartet auf Rückmeldung.")

    @discord.ui.button(
        label="Schließen",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="zyrahd:ticket:close",
    )
    async def close(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        ticket_id = self._id_from_channel(interaction)
        with session_scope() as db:
            ticket = db.get(Ticket, ticket_id) if ticket_id else None
            if not ticket or ticket.status in ("closed", "archived"):
                await interaction.response.send_message(
                    "Dieses Ticket ist bereits geschlossen.", ephemeral=True
                )
                return
            is_owner = ticket.creator_id == str(interaction.user.id)
            can_manage = interaction.user.guild_permissions.manage_messages
            if not is_owner and not can_manage:
                await interaction.response.send_message(
                    "Du darfst dieses Ticket nicht schließen.", ephemeral=True
                )
                return
            ticket.status = "closed"
            ticket.closed_reason = "Über Discord geschlossen"
            ticket.closed_at = datetime.now(timezone.utc)
            ticket.updated_at = ticket.closed_at
            creator_id = int(ticket.creator_id)
        if isinstance(interaction.channel, discord.TextChannel):
            member = interaction.guild.get_member(creator_id) if interaction.guild else None
            if member:
                await interaction.channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    reason=f"Ticket #{ticket_id} geschlossen",
                )
        await interaction.response.send_message(
            f"🔒 Ticket geschlossen von {interaction.user.mention}."
        )
