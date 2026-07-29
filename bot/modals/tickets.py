"""Ticket-Formulare als Discord Modals."""

from __future__ import annotations

import discord


class TicketFormModal(discord.ui.Modal):
    def __init__(self, ticket_type_id: int, type_name: str, fields: list[dict]):
        super().__init__(title=f"{type_name}"[:45])
        self.ticket_type_id = ticket_type_id
        self.field_meta = fields
        self.inputs: list[discord.ui.TextInput] = []

        for field in fields[:5]:
            style = (
                discord.TextStyle.paragraph
                if field.get("field_type") == "long"
                else discord.TextStyle.short
            )
            max_length = max(1, min(int(field.get("max_length") or 1000), 1000))
            min_length = max(0, min(int(field.get("min_length") or 0), max_length))
            ti = discord.ui.TextInput(
                label=field["label"][:45],
                placeholder=(field.get("placeholder") or "")[:100],
                required=bool(field.get("required", True)),
                style=style,
                min_length=min_length if field.get("required") else 0,
                max_length=max_length,
            )
            self.inputs.append(ti)
            self.add_item(ti)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        form_data = {}
        for meta, ti in zip(self.field_meta, self.inputs):
            form_data[meta["label"]] = ti.value

        from bot.cogs.tickets import create_ticket_channel

        try:
            result = await create_ticket_channel(
                interaction.client,
                {
                    "ticket_type_id": self.ticket_type_id,
                    "opener_id": interaction.user.id,
                    "opener_name": str(interaction.user),
                    "form_data": form_data,
                },
            )
            channel_id = result.get("channel_id")
            await interaction.followup.send(
                f"Ticket erstellt: <#{channel_id}>",
                ephemeral=True,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Fehler: {exc}", ephemeral=True)
