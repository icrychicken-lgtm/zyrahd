"""Persistent ticket panel, dynamic type selector, and form modal."""

from __future__ import annotations

from typing import Any

import discord
from sqlalchemy import select

from database.manager import session_scope
from database.models import TicketType


class TicketFormModal(discord.ui.Modal):
    def __init__(self, ticket_type: TicketType) -> None:
        super().__init__(title=f"{ticket_type.emoji} {ticket_type.name}"[:45])
        self.ticket_type_id = ticket_type.id
        fields = ticket_type.form_fields[:5]
        if not fields:
            fields = [
                {
                    "id": "request",
                    "label": "Beschreibe deine Anfrage",
                    "type": "long",
                    "required": True,
                    "max_length": 1000,
                }
            ]
        self.field_map: dict[str, discord.ui.TextInput[Any]] = {}
        for field in fields:
            key = str(field.get("id", f"field_{len(self.field_map)}"))
            item = discord.ui.TextInput(
                label=str(field.get("label", key))[:45],
                placeholder=str(field.get("placeholder", ""))[:100] or None,
                style=(
                    discord.TextStyle.paragraph
                    if field.get("type") == "long"
                    else discord.TextStyle.short
                ),
                required=bool(field.get("required", False)),
                min_length=max(0, int(field.get("min_length", 0) or 0)) or None,
                max_length=min(4000, int(field.get("max_length", 1000) or 1000)),
            )
            self.add_item(item)
            self.field_map[key] = item

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await interaction.client.create_dashboard_ticket(
                ticket_type_id=self.ticket_type_id,
                creator_id=interaction.user.id,
                creator_name=interaction.user.display_name,
                answers={key: item.value for key, item in self.field_map.items()},
            )
        except (ValueError, PermissionError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            await interaction.followup.send(
                "Das Ticket konnte nicht erstellt werden. Bitte informiere das Team.",
                ephemeral=True,
            )
            raise
        channel = interaction.guild.get_channel(int(result["channel_id"]))
        await interaction.followup.send(
            f"Dein Ticket wurde erstellt: {channel.mention if channel else '#Ticket'}",
            ephemeral=True,
        )


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, types: list[TicketType]) -> None:
        options = [
            discord.SelectOption(
                label=item.name[:100],
                description=item.description[:100] or None,
                emoji=item.emoji or None,
                value=str(item.id),
            )
            for item in types[:25]
        ]
        super().__init__(
            placeholder="Wähle den passenden Bereich …",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        with session_scope() as db:
            item = db.get(TicketType, int(self.values[0]))
            if not item or not item.enabled:
                await interaction.response.send_message(
                    "Diese Ticket-Art ist nicht mehr verfügbar.", ephemeral=True
                )
                return
            db.expunge(item)
        await interaction.response.send_modal(TicketFormModal(item))


class TicketTypeView(discord.ui.View):
    def __init__(self, types: list[TicketType]) -> None:
        super().__init__(timeout=120)
        self.add_item(TicketTypeSelect(types))


class TicketPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ticket erstellen",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="zyrahd:ticket:create",
    )
    async def create(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "Tickets können nur auf dem Server erstellt werden.", ephemeral=True
            )
            return
        with session_scope() as db:
            types = list(
                db.scalars(
                    select(TicketType)
                    .where(
                        TicketType.guild_id == str(interaction.guild_id),
                        TicketType.enabled.is_(True),
                    )
                    .order_by(TicketType.id)
                )
            )
            for item in types:
                db.expunge(item)
        if not types:
            await interaction.response.send_message(
                "Aktuell sind keine Ticket-Arten aktiviert.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Womit können wir dir helfen?",
            view=TicketTypeView(types),
            ephemeral=True,
        )
