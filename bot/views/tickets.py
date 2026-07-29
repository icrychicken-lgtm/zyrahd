"""Discord-Views für das Ticket-System."""

from __future__ import annotations

from typing import Optional

import discord

from database.manager import get_session
from database.models import TicketType


class TicketPanelView(discord.ui.View):
    def __init__(self, button_label: str = "🎫 Ticket erstellen"):
        super().__init__(timeout=None)
        self.add_item(TicketCreateButton(button_label))


class TicketCreateButton(discord.ui.Button):
    def __init__(self, label: str = "🎫 Ticket erstellen"):
        super().__init__(
            label=label[:80],
            style=discord.ButtonStyle.primary,
            custom_id="zyrahd:ticket:create",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        options = []
        with get_session() as session:
            types = (
                session.query(TicketType)
                .filter(TicketType.enabled.is_(True))
                .order_by(TicketType.sort_order.asc(), TicketType.id.asc())
                .all()
            )
            for tt in types[:25]:
                emoji = None
                if tt.emoji and len(tt.emoji) <= 2:
                    try:
                        emoji = tt.emoji
                    except Exception:
                        emoji = None
                options.append(
                    discord.SelectOption(
                        label=tt.name[:100],
                        description=(tt.description or "")[:100],
                        value=str(tt.id),
                        emoji=emoji,
                    )
                )

        if not options:
            await interaction.response.send_message(
                "Aktuell sind keine Ticket-Arten verfügbar.", ephemeral=True
            )
            return

        view = discord.ui.View(timeout=120)
        view.add_item(TicketTypeSelect(options))
        await interaction.response.send_message(
            "Wähle den passenden Bereich:", view=view, ephemeral=True
        )


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(
            placeholder="Ticket-Art wählen…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="zyrahd:ticket:type",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from bot.modals.tickets import TicketFormModal

        type_id = int(self.values[0])
        with get_session() as session:
            tt = session.get(TicketType, type_id)
            if not tt or not tt.enabled:
                await interaction.response.send_message(
                    "Diese Ticket-Art ist nicht verfügbar.", ephemeral=True
                )
                return
            fields = sorted(tt.fields, key=lambda f: f.sort_order)
            # Snapshot für Modal
            field_data = [
                {
                    "id": f.id,
                    "label": f.label,
                    "field_type": f.field_type,
                    "placeholder": f.placeholder,
                    "required": f.required,
                    "min_length": f.min_length,
                    "max_length": min(f.max_length or 1000, 1000),
                    "options": f.get_options(),
                }
                for f in fields[:5]  # Discord Modal Limit
            ]
            type_name = tt.name

        modal = TicketFormModal(ticket_type_id=type_id, type_name=type_name, fields=field_data)
        await interaction.response.send_modal(modal)


class TicketControlView(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    @discord.ui.button(label="Übernehmen", style=discord.ButtonStyle.success, custom_id="zyrahd:ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._action(interaction, "claim")

    @discord.ui.button(label="Schließen", style=discord.ButtonStyle.danger, custom_id="zyrahd:ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._action(interaction, "close")

    async def _action(self, interaction: discord.Interaction, action: str) -> None:
        # ticket_id aus Channel auflösen
        from bot.cogs.tickets import perform_ticket_action

        with get_session() as session:
            from database.models import Ticket

            ticket = (
                session.query(Ticket)
                .filter(Ticket.channel_id == interaction.channel_id)
                .order_by(Ticket.id.desc())
                .first()
            )
            if not ticket:
                await interaction.response.send_message("Ticket nicht gefunden.", ephemeral=True)
                return
            ticket_id = ticket.id

        try:
            result = await perform_ticket_action(
                interaction.client,
                {
                    "ticket_id": ticket_id,
                    "action": action,
                    "actor_id": interaction.user.id,
                    "actor_name": str(interaction.user),
                    "reason": "Über Discord-Button",
                },
            )
            await interaction.response.send_message(
                result.get("message", "Aktion ausgeführt."), ephemeral=True
            )
        except Exception as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
