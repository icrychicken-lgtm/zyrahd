"""Audited moderation slash commands."""

from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from database.manager import session_scope
from database.models import ModerationCase


def create_case(
    guild_id: int,
    target: discord.abc.User,
    moderator: discord.abc.User,
    action: str,
    reason: str,
    duration_seconds: int | None = None,
) -> int:
    with session_scope() as session:
        number = (
            session.scalar(
                select(func.max(ModerationCase.case_number)).where(
                    ModerationCase.guild_id == str(guild_id)
                )
            )
            or 0
        ) + 1
        session.add(
            ModerationCase(
                guild_id=str(guild_id),
                case_number=number,
                target_id=str(target.id),
                target_name=str(target),
                moderator_id=str(moderator.id),
                moderator_name=str(moderator),
                action=action,
                reason=reason,
                duration_seconds=duration_seconds,
            )
        )
        return number


class ModerationCog(commands.Cog, name="ModerationCog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="warn", description="Verwarne ein Mitglied")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        number = create_case(
            interaction.guild_id, member, interaction.user, "warn", reason
        )
        try:
            await member.send(
                f"Du wurdest auf **{interaction.guild.name}** verwarnt.\n"
                f"Grund: {reason}\nFall #{number}"
            )
        except discord.Forbidden:
            pass
        await interaction.response.send_message(
            f"✅ {member.mention} wurde verwarnt · Fall **#{number}**"
        )

    @app_commands.command(
        name="warnings", description="Zeige Verwarnungen eines Mitglieds"
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        with session_scope() as session:
            cases = list(
                session.scalars(
                    select(ModerationCase)
                    .where(
                        ModerationCase.guild_id == str(interaction.guild_id),
                        ModerationCase.target_id == str(member.id),
                        ModerationCase.action == "warn",
                        ModerationCase.active.is_(True),
                    )
                    .order_by(ModerationCase.created_at.desc())
                    .limit(10)
                )
            )
        description = "\n".join(
            f"**#{case.case_number}** · {case.reason} — {case.moderator_name}"
            for case in cases
        )
        embed = discord.Embed(
            title=f"Verwarnungen · {member}",
            description=description or "Keine aktiven Verwarnungen.",
            color=0x8B5CF6,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="unwarn", description="Hebe eine Verwarnung auf")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unwarn(self, interaction: discord.Interaction, fallnummer: int) -> None:
        with session_scope() as session:
            case = session.scalar(
                select(ModerationCase).where(
                    ModerationCase.guild_id == str(interaction.guild_id),
                    ModerationCase.case_number == fallnummer,
                    ModerationCase.action == "warn",
                )
            )
            if not case:
                await interaction.response.send_message(
                    "Fall nicht gefunden.", ephemeral=True
                )
                return
            case.active = False
        await interaction.response.send_message(
            f"✅ Verwarnung **#{fallnummer}** wurde aufgehoben."
        )

    @app_commands.command(
        name="timeout", description="Gib einem Mitglied einen Timeout"
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        minuten: app_commands.Range[int, 1, 40320],
        reason: str,
    ) -> None:
        await member.timeout(timedelta(minutes=minuten), reason=reason)
        number = create_case(
            interaction.guild_id,
            member,
            interaction.user,
            "timeout",
            reason,
            minuten * 60,
        )
        await interaction.response.send_message(
            f"⏱️ {member.mention} hat {minuten} Minuten Timeout · Fall **#{number}**"
        )

    @app_commands.command(name="untimeout", description="Entferne einen Timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Aufgehoben",
    ) -> None:
        await member.timeout(None, reason=reason)
        number = create_case(
            interaction.guild_id, member, interaction.user, "untimeout", reason
        )
        await interaction.response.send_message(
            f"✅ Timeout für {member.mention} entfernt · Fall **#{number}**"
        )

    @app_commands.command(name="kick", description="Entferne ein Mitglied vom Server")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        number = create_case(
            interaction.guild_id, member, interaction.user, "kick", reason
        )
        await member.kick(reason=reason)
        await interaction.response.send_message(
            f"👢 {member} wurde gekickt · Fall **#{number}**"
        )

    @app_commands.command(name="ban", description="Sperre ein Mitglied")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        number = create_case(
            interaction.guild_id, member, interaction.user, "ban", reason
        )
        await member.ban(reason=reason, delete_message_seconds=0)
        await interaction.response.send_message(
            f"🔨 {member} wurde gebannt · Fall **#{number}**"
        )

    @app_commands.command(name="unban", description="Hebe einen Ban per Discord-ID auf")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(
        self,
        interaction: discord.Interaction,
        benutzer_id: str,
        reason: str = "Aufgehoben",
    ) -> None:
        if not benutzer_id.isdigit():
            await interaction.response.send_message(
                "Die Benutzer-ID ist ungültig.", ephemeral=True
            )
            return
        user = await self.bot.fetch_user(int(benutzer_id))
        await interaction.guild.unban(user, reason=reason)
        number = create_case(
            interaction.guild_id, user, interaction.user, "unban", reason
        )
        await interaction.response.send_message(
            f"✅ Ban für {user} aufgehoben · Fall **#{number}**"
        )

    @app_commands.command(
        name="clear", description="Lösche Nachrichten im aktuellen Kanal"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        anzahl: app_commands.Range[int, 1, 100],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(
                "Dieser Kanal wird nicht unterstützt.", ephemeral=True
            )
            return
        deleted = await interaction.channel.purge(limit=anzahl)
        await interaction.followup.send(
            f"🧹 {len(deleted)} Nachrichten gelöscht.", ephemeral=True
        )

    @app_commands.command(name="slowmode", description="Setze den Slowmode")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(
        self,
        interaction: discord.Interaction,
        sekunden: app_commands.Range[int, 0, 21600],
    ) -> None:
        await interaction.channel.edit(slowmode_delay=sekunden)
        await interaction.response.send_message(f"✅ Slowmode: **{sekunden}s**")

    @app_commands.command(name="lock", description="Sperre den aktuellen Kanal")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction) -> None:
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(
            interaction.guild.default_role, overwrite=overwrite
        )
        await interaction.response.send_message("🔒 Kanal gesperrt.")

    @app_commands.command(name="unlock", description="Entsperre den aktuellen Kanal")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(
            interaction.guild.default_role, overwrite=overwrite
        )
        await interaction.response.send_message("🔓 Kanal entsperrt.")

    @app_commands.command(
        name="nickname", description="Ändere den Nickname eines Mitglieds"
    )
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def nickname(
        self, interaction: discord.Interaction, member: discord.Member, nickname: str
    ) -> None:
        await member.edit(nick=nickname[:32] or None)
        await interaction.response.send_message(
            f"✅ Nickname von {member.mention} aktualisiert."
        )

    @app_commands.command(name="case", description="Zeige einen Moderationsfall")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def case(self, interaction: discord.Interaction, fallnummer: int) -> None:
        with session_scope() as session:
            item = session.scalar(
                select(ModerationCase).where(
                    ModerationCase.guild_id == str(interaction.guild_id),
                    ModerationCase.case_number == fallnummer,
                )
            )
        if not item:
            await interaction.response.send_message(
                "Fall nicht gefunden.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title=f"Moderationsfall #{item.case_number}",
            color=0x8B5CF6,
            timestamp=item.created_at,
        )
        embed.add_field(name="Aktion", value=item.action.title())
        embed.add_field(name="Nutzer", value=f"{item.target_name} (`{item.target_id}`)")
        embed.add_field(name="Moderator", value=item.moderator_name)
        embed.add_field(name="Grund", value=item.reason, inline=False)
        embed.add_field(name="Status", value="Aktiv" if item.active else "Aufgehoben")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        message = (
            "Dafür fehlen dir die benötigten Discord-Berechtigungen."
            if isinstance(error, app_commands.MissingPermissions)
            else f"Aktion fehlgeschlagen: {error}"
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
