"""Utility commands and persistent verification interaction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from database.manager import get_setting, session_scope


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
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Die Verifizierung funktioniert nur auf dem Server.", ephemeral=True
            )
            return
        with session_scope() as session:
            config = get_setting(session, str(interaction.guild.id), "verify", {})
        role_id = str(config.get("role_id") or "")
        role = (
            interaction.guild.get_role(int(role_id)) if role_id.isdigit() else None
        )
        if not role:
            await interaction.response.send_message(
                "Das Verify-System wurde noch nicht vollständig eingerichtet.",
                ephemeral=True,
            )
            return
        minimum_days = max(0, int(config.get("minimum_account_age", 0)))
        if interaction.user.created_at > datetime.now(UTC) - timedelta(
            days=minimum_days
        ):
            await interaction.response.send_message(
                f"Dein Account muss mindestens {minimum_days} Tage alt sein.",
                ephemeral=True,
            )
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Die Verify-Rolle liegt über der Bot-Rolle.", ephemeral=True
            )
            return
        remove_roles = []
        for item in config.get("remove_role_ids", []):
            current = interaction.guild.get_role(int(item))
            if current and current < interaction.guild.me.top_role:
                remove_roles.append(current)
        await interaction.user.add_roles(role, reason="Zyrahd Verifizierung")
        if remove_roles:
            await interaction.user.remove_roles(
                *remove_roles, reason="Zyrahd Verifizierung"
            )
        await interaction.response.send_message(
            f"✅ Du wurdest erfolgreich als **{role.name}** verifiziert.", ephemeral=True
        )
        if config.get("send_dm"):
            try:
                await interaction.user.send(
                    f"Du wurdest auf **{interaction.guild.name}** erfolgreich verifiziert."
                )
            except discord.Forbidden:
                pass


class UtilityCog(commands.Cog, name="UtilityCog"):
    role = app_commands.Group(
        name="role",
        description="Rollen eines Mitglieds verwalten",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(VerifyView())

    @app_commands.command(name="ping", description="Zeige den Status des Bots")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"💜 Zyrahd ist online · **{round(self.bot.latency * 1000)} ms**",
            ephemeral=True,
        )

    @role.command(name="add", description="Gib einem Mitglied eine Rolle")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: discord.Role,
    ) -> None:
        if role >= interaction.guild.me.top_role or role.managed:
            await interaction.response.send_message(
                "Diese Rolle kann der Bot nicht vergeben.", ephemeral=True
            )
            return
        await member.add_roles(role, reason=f"Von {interaction.user} vergeben")
        await interaction.response.send_message(
            f"✅ {role.mention} wurde {member.mention} gegeben."
        )

    @role.command(name="remove", description="Entferne eine Rolle")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_remove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: discord.Role,
    ) -> None:
        if role >= interaction.guild.me.top_role or role.managed:
            await interaction.response.send_message(
                "Diese Rolle kann der Bot nicht entfernen.", ephemeral=True
            )
            return
        await member.remove_roles(role, reason=f"Von {interaction.user} entfernt")
        await interaction.response.send_message(
            f"✅ {role.mention} wurde von {member.mention} entfernt."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
