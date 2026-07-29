"""Persistent verify button configured from the dashboard."""

from __future__ import annotations

import discord

from database.manager import get_setting


class VerifyView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verifizieren",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="zyrahd:verify",
    )
    async def verify(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Die Verifizierung ist nur auf dem Server möglich.", ephemeral=True
            )
            return
        config = get_setting(str(interaction.guild.id), "verify", {})
        if not config.get("enabled", True):
            await interaction.response.send_message(
                "Die Verifizierung ist momentan deaktiviert.", ephemeral=True
            )
            return
        role_id = config.get("role_id")
        role = interaction.guild.get_role(int(role_id)) if role_id else None
        if not role or role.managed:
            await interaction.response.send_message(
                "Die Verifizierungsrolle ist nicht korrekt eingerichtet.", ephemeral=True
            )
            return
        account_days = max(0, int(config.get("minimum_account_age_days", 0)))
        age_days = (discord.utils.utcnow() - interaction.user.created_at).days
        if age_days < account_days:
            await interaction.response.send_message(
                f"Dein Discord-Konto muss mindestens {account_days} Tage alt sein.",
                ephemeral=True,
            )
            return
        try:
            await interaction.user.add_roles(role, reason="zyrahd Verifizierung")
            removable = [
                interaction.guild.get_role(int(item))
                for item in config.get("remove_role_ids", [])
            ]
            removable = [
                item for item in removable if item and not item.managed and item != role
            ]
            if removable:
                await interaction.user.remove_roles(
                    *removable, reason="zyrahd Verifizierung"
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Ich kann die Rolle nicht vergeben. Prüfe meine Rollenposition.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Du wurdest erfolgreich verifiziert. Willkommen!", ephemeral=True
        )
        if config.get("success_dm"):
            try:
                await interaction.user.send(str(config["success_dm"])[:2000])
            except discord.HTTPException:
                pass
