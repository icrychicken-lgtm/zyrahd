"""Moderations-Slash-Commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from bot.utils.helpers import format_duration
from database.manager import get_session
from database.models import ModCase


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _mod_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.moderate_members:
            return False
        return True

    async def _create_case(
        self,
        *,
        user: discord.abc.User,
        moderator: discord.abc.User,
        action: str,
        reason: str,
        duration: int | None = None,
        evidence: str = "",
    ) -> ModCase:
        with get_session() as session:
            last = session.query(ModCase).order_by(ModCase.case_number.desc()).first()
            case_number = (last.case_number + 1) if last else 1
            expires = None
            if duration:
                expires = datetime.now(timezone.utc) + timedelta(seconds=duration)
            case = ModCase(
                case_number=case_number,
                user_id=user.id,
                user_name=str(user),
                moderator_id=moderator.id,
                moderator_name=str(moderator),
                action=action,
                reason=reason or "Kein Grund angegeben",
                evidence=evidence,
                duration_seconds=duration,
                expires_at=expires,
            )
            session.add(case)
            session.flush()
            session.refresh(case)
            # detach values
            return type("Case", (), {"case_number": case.case_number, "id": case.id})()

    @app_commands.command(name="warn", description="Benutzer verwarnen")
    @app_commands.describe(user="Benutzer", reason="Grund")
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund angegeben"):
        if not self._mod_check(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        case = await self._create_case(user=user, moderator=interaction.user, action="warn", reason=reason)
        await interaction.response.send_message(
            f"⚠️ {user.mention} wurde verwarnt. Fall #{case.case_number}\nGrund: {reason}",
            ephemeral=False,
        )
        try:
            await user.send(f"Du wurdest auf **{interaction.guild.name}** verwarnt.\nGrund: {reason}")
        except discord.HTTPException:
            pass

    @app_commands.command(name="warnings", description="Verwarnungen eines Benutzers anzeigen")
    async def warnings(self, interaction: discord.Interaction, user: discord.Member):
        if not self._mod_check(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        with get_session() as session:
            cases = (
                session.query(ModCase)
                .filter(ModCase.user_id == user.id, ModCase.action == "warn", ModCase.status == "active")
                .order_by(ModCase.created_at.desc())
                .limit(15)
                .all()
            )
            if not cases:
                await interaction.response.send_message(f"{user.mention} hat keine aktiven Verwarnungen.", ephemeral=True)
                return
            lines = [f"**#{c.case_number}** – {c.reason} ({c.moderator_name})" for c in cases]
        await interaction.response.send_message(
            f"Verwarnungen für {user.mention}:\n" + "\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="unwarn", description="Verwarnung aufheben")
    async def unwarn(self, interaction: discord.Interaction, case_number: int, reason: str = "Aufgehoben"):
        if not self._mod_check(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        with get_session() as session:
            case = session.query(ModCase).filter(ModCase.case_number == case_number).first()
            if not case:
                await interaction.response.send_message("Fall nicht gefunden.", ephemeral=True)
                return
            case.status = "revoked"
            case.revoked_by = interaction.user.id
            case.revoked_at = datetime.now(timezone.utc)
            case.revoke_reason = reason
        await interaction.response.send_message(f"Fall #{case_number} aufgehoben.", ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout vergeben")
    async def timeout(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        reason: str = "Kein Grund angegeben",
    ):
        if not self._mod_check(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        try:
            await user.timeout(until, reason=reason)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return
        case = await self._create_case(
            user=user, moderator=interaction.user, action="timeout", reason=reason, duration=minutes * 60
        )
        await interaction.response.send_message(
            f"🔇 {user.mention} Timeout für {minutes} Min. Fall #{case.case_number}"
        )

    @app_commands.command(name="untimeout", description="Timeout entfernen")
    async def untimeout(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Timeout entfernt"):
        if not self._mod_check(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            await user.timeout(None, reason=reason)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return
        await self._create_case(user=user, moderator=interaction.user, action="untimeout", reason=reason)
        await interaction.response.send_message(f"Timeout von {user.mention} entfernt.")

    @app_commands.command(name="kick", description="Benutzer kicken")
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund angegeben"):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            await user.kick(reason=reason)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return
        case = await self._create_case(user=user, moderator=interaction.user, action="kick", reason=reason)
        await interaction.response.send_message(f"👢 {user} gekickt. Fall #{case.case_number}")

    @app_commands.command(name="ban", description="Benutzer bannen")
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: str = "Kein Grund angegeben"):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            await interaction.guild.ban(user, reason=reason, delete_message_days=0)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return
        case = await self._create_case(user=user, moderator=interaction.user, action="ban", reason=reason)
        await interaction.response.send_message(f"🔨 {user} gebannt. Fall #{case.case_number}")

    @app_commands.command(name="tempban", description="Temporären Bann vergeben")
    async def tempban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        days: app_commands.Range[int, 1, 365],
        reason: str = "Kein Grund angegeben",
    ):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            await interaction.guild.ban(user, reason=reason, delete_message_days=0)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return
        case = await self._create_case(
            user=user, moderator=interaction.user, action="tempban", reason=reason, duration=days * 86400
        )
        await interaction.response.send_message(
            f"🔨 {user} für {days} Tag(e) gebannt. Fall #{case.case_number}"
        )

    @app_commands.command(name="unban", description="Bann aufheben")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Entbannt"):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            uid = int(user_id)
            await interaction.guild.unban(discord.Object(id=uid), reason=reason)
        except Exception as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return
        await self._create_case(
            user=discord.Object(id=uid),  # type: ignore
            moderator=interaction.user,
            action="unban",
            reason=reason,
        )
        # Fix user fields manually
        with get_session() as session:
            last = session.query(ModCase).order_by(ModCase.id.desc()).first()
            if last and last.action == "unban":
                last.user_id = uid
                last.user_name = str(uid)
        await interaction.response.send_message(f"Benutzer `{uid}` entbannt.")

    @app_commands.command(name="clear", description="Nachrichten löschen")
    async def clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True)

    @app_commands.command(name="slowmode", description="Slowmode setzen")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        await interaction.channel.edit(slowmode_delay=seconds)
        await interaction.response.send_message(f"Slowmode: {seconds}s")

    @app_commands.command(name="lock", description="Kanal sperren")
    async def lock(self, interaction: discord.Interaction, reason: str = "Lockdown"):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)
        await interaction.response.send_message("🔒 Kanal gesperrt.")

    @app_commands.command(name="unlock", description="Kanal entsperren")
    async def unlock(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 Kanal entsperrt.")

    @app_commands.command(name="nickname", description="Nickname ändern")
    async def nickname(self, interaction: discord.Interaction, user: discord.Member, nick: str = ""):
        if not interaction.user.guild_permissions.manage_nicknames:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            await user.edit(nick=nick or None, reason=f"Von {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"Nickname von {user.mention} geändert.")

    role_group = app_commands.Group(name="role", description="Rollen verwalten")

    @role_group.command(name="add", description="Rolle hinzufügen")
    async def role_add(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            await user.add_roles(role, reason=f"Von {interaction.user}")
            await interaction.response.send_message(f"{role.mention} an {user.mention} vergeben.")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)

    @role_group.command(name="remove", description="Rolle entfernen")
    async def role_remove(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        try:
            await user.remove_roles(role, reason=f"Von {interaction.user}")
            await interaction.response.send_message(f"{role.mention} von {user.mention} entfernt.")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)

    @app_commands.command(name="case", description="Moderationsfall anzeigen")
    async def case_cmd(self, interaction: discord.Interaction, case_number: int):
        with get_session() as session:
            case = session.query(ModCase).filter(ModCase.case_number == case_number).first()
            if not case:
                await interaction.response.send_message("Fall nicht gefunden.", ephemeral=True)
                return
            embed = discord.Embed(title=f"Fall #{case.case_number}", color=0x9B5CFF)
            embed.add_field(name="Aktion", value=case.action, inline=True)
            embed.add_field(name="Status", value=case.status, inline=True)
            embed.add_field(name="Benutzer", value=f"{case.user_name} (`{case.user_id}`)", inline=False)
            embed.add_field(name="Moderator", value=case.moderator_name, inline=True)
            embed.add_field(name="Dauer", value=format_duration(case.duration_seconds), inline=True)
            embed.add_field(name="Grund", value=case.reason or "—", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
