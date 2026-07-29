"""Slash commands for common moderation actions."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def execute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        action: str,
        reason: str,
        duration_minutes: int = 10,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.bot.service.moderate(
                {
                    "user_id": str(member.id),
                    "action": action,
                    "reason": reason,
                    "duration_minutes": duration_minutes,
                    "moderator_id": str(interaction.user.id),
                    "moderator_name": interaction.user.display_name,
                }
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"Aktion ausgeführt · **{result['case']['case_number']}**", ephemeral=True
        )

    @app_commands.command(name="warn", description="Verwarnt ein Mitglied.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ) -> None:
        await self.execute(interaction, member, "warn", reason)

    @app_commands.command(name="timeout", description="Gibt einem Mitglied Timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        reason: str,
    ) -> None:
        await self.execute(interaction, member, "timeout", reason, minutes)

    @app_commands.command(name="untimeout", description="Entfernt einen Timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Timeout aufgehoben",
    ) -> None:
        await self.execute(interaction, member, "untimeout", reason)

    @app_commands.command(name="kick", description="Entfernt ein Mitglied vom Server.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ) -> None:
        await self.execute(interaction, member, "kick", reason)

    @app_commands.command(name="ban", description="Bannt ein Mitglied.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ) -> None:
        await self.execute(interaction, member, "ban", reason)

    @app_commands.command(name="clear", description="Löscht Nachrichten im Kanal.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Dieser Befehl funktioniert nur in Textkanälen.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(
            f"{len(deleted)} Nachricht(en) gelöscht.", ephemeral=True
        )

    @app_commands.command(name="lock", description="Sperrt den aktuellen Kanal.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Dieser Befehl funktioniert nur in Textkanälen.", ephemeral=True
            )
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"Gesperrt von {interaction.user}",
        )
        await interaction.response.send_message("🔒 Kanal gesperrt.")

    @app_commands.command(name="unlock", description="Entsperrt den aktuellen Kanal.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Dieser Befehl funktioniert nur in Textkanälen.", ephemeral=True
            )
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"Entsperrt von {interaction.user}",
        )
        await interaction.response.send_message("🔓 Kanal entsperrt.")

    @app_commands.command(name="slowmode", description="Setzt den Kanal-Slowmode.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Dieser Befehl funktioniert nur in Textkanälen.", ephemeral=True
            )
            return
        await interaction.channel.edit(
            slowmode_delay=seconds, reason=f"Geändert von {interaction.user}"
        )
        await interaction.response.send_message(
            f"Slowmode: **{seconds} Sekunden**.", ephemeral=True
        )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        message = (
            "Dir fehlt die benötigte Discord-Berechtigung."
            if isinstance(error, app_commands.MissingPermissions)
            else "Der Befehl konnte nicht ausgeführt werden."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
