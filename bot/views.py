"""Persistent Discord components used by the ticket and verify systems."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.services import BotService


class TicketPanelView(discord.ui.View):
    def __init__(self, service: BotService):
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(
        label="Ticket erstellen",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="zyrahd:ticket:create",
    )
    async def create_ticket(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        options = self.service.ticket_type_options()
        if not options:
            await interaction.response.send_message(
                "Aktuell ist keine Ticket-Art verfügbar.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Wähle den passenden Bereich:",
            view=TicketTypeSelectView(self.service, options),
            ephemeral=True,
        )


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, service: BotService, options: list[discord.SelectOption]):
        self.service = service
        super().__init__(
            placeholder="Ticket-Art auswählen …",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        ticket_type = self.service.get_ticket_type(int(self.values[0]))
        if ticket_type is None or not ticket_type.enabled:
            await interaction.response.edit_message(
                content="Diese Ticket-Art ist nicht mehr verfügbar.", view=None
            )
            return
        await interaction.response.send_modal(TicketModal(self.service, ticket_type))


class TicketTypeSelectView(discord.ui.View):
    def __init__(
        self, service: BotService, options: list[discord.SelectOption]
    ) -> None:
        super().__init__(timeout=180)
        self.add_item(TicketTypeSelect(service, options))


class TicketModal(discord.ui.Modal):
    def __init__(self, service: BotService, ticket_type):
        super().__init__(title=ticket_type.name[:45], timeout=600)
        self.service = service
        self.ticket_type_id = ticket_type.id
        fields = (ticket_type.form_fields or [])[:5]
        if not fields:
            fields = [
                {
                    "id": "reason",
                    "label": "Wie können wir dir helfen?",
                    "type": "long",
                    "required": True,
                    "max_length": 1000,
                }
            ]
        self.field_ids: list[str] = []
        for field in fields:
            self.field_ids.append(field["id"])
            self.add_item(
                discord.ui.TextInput(
                    label=field["label"][:45],
                    placeholder=(field.get("placeholder") or None),
                    required=bool(field.get("required", True)),
                    min_length=min(int(field.get("min_length", 0)), 4000),
                    max_length=min(int(field.get("max_length", 1000)), 4000),
                    style=(
                        discord.TextStyle.paragraph
                        if field.get("type") == "long"
                        else discord.TextStyle.short
                    ),
                )
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        answers = {
            field_id: str(component.value)
            for field_id, component in zip(self.field_ids, self.children, strict=True)
        }
        try:
            ticket = await self.service.create_ticket(
                self.ticket_type_id,
                interaction.user.id,
                interaction.user.display_name,
                answers,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"Dein Ticket wurde erstellt: <#{ticket.channel_id}>", ephemeral=True
        )


class TicketControlView(discord.ui.View):
    def __init__(self, service: BotService):
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(
        label="Übernehmen",
        emoji="🙋",
        style=discord.ButtonStyle.secondary,
        custom_id="zyrahd:ticket:claim",
    )
    async def claim(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        try:
            message = self.service.claim_ticket(
                interaction.channel_id, interaction.user
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(message)

    @discord.ui.button(
        label="Schließen",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="zyrahd:ticket:close",
    )
    async def close(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.service.close_ticket_by_channel(
                interaction.channel_id,
                interaction.user.id,
                "Über Discord geschlossen",
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("Ticket wurde geschlossen.", ephemeral=True)


class VerifyView(discord.ui.View):
    def __init__(self, service: BotService, label: str = "Verifizieren", emoji="✅"):
        super().__init__(timeout=None)
        self.service = service
        button = discord.ui.Button(
            label=label[:80],
            emoji=emoji or None,
            style=discord.ButtonStyle.success,
            custom_id="zyrahd:verify",
        )
        button.callback = self.verify
        self.add_item(button)

    async def verify(self, interaction: discord.Interaction) -> None:
        try:
            message = await self.service.verify_member(interaction.user)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(message, ephemeral=True)


class AnnouncementConfirmView(discord.ui.View):
    def __init__(self, service: BotService, announcement_id: int):
        super().__init__(timeout=None)
        self.service = service
        self.announcement_id = announcement_id
        button = discord.ui.Button(
            label="Gelesen & bestätigt",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"zyrahd:announcement:{announcement_id}:confirm",
        )
        button.callback = self.confirm
        self.add_item(button)

    async def confirm(self, interaction: discord.Interaction) -> None:
        created = self.service.confirm_announcement(
            self.announcement_id, interaction.user
        )
        message = (
            "Danke, deine Bestätigung wurde gespeichert."
            if created
            else "Du hast diese Ankündigung bereits bestätigt."
        )
        await interaction.response.send_message(message, ephemeral=True)
