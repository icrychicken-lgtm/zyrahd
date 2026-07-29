"""Moderation slash commands with numbered, persistent cases."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from database.manager import session_scope
from database.models import ModerationCase


def parse_duration(value: str) -> timedelta:
    match = re.fullmatch(r"\s*(\d+)\s*([mhdw])\s*", value.lower())
    if not match:
        raise ValueError("Nutze eine Dauer wie 30m, 12h, 7d oder 2w.")
    amount = int(match.group(1))
    if amount < 1:
        raise ValueError("Die Dauer muss größer als null sein.")
    units = {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }
    result = units[match.group(2)]
    if result > timedelta(days=28):
        raise ValueError("Discord-Timeouts dürfen höchstens 28 Tage dauern.")
    return result


class ModerationCog(commands.Cog):
    role = app_commands.Group(name="role", description="Rollen verwalten")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.expire_tempbans.start()

    def cog_unload(self) -> None:
        self.expire_tempbans.cancel()

    def record(
        self,
        interaction: discord.Interaction,
        target: discord.abc.User,
        action: str,
        reason: str,
        duration: timedelta | None = None,
    ) -> int:
        with session_scope() as db:
            row = ModerationCase(
                guild_id=str(interaction.guild_id),
                user_id=str(target.id),
                user_name=str(target),
                moderator_id=str(interaction.user.id),
                moderator_name=interaction.user.display_name,
                action=action,
                reason=reason,
                duration_minutes=int(duration.total_seconds() // 60)
                if duration
                else None,
            )
            db.add(row)
            db.flush()
            return row.id

    async def respond(
        self, interaction: discord.Interaction, case_id: int, text: str
    ) -> None:
        await interaction.response.send_message(f"**Fall #{case_id}** · {text}")

    @app_commands.command(name="warn", description="Verwarnt ein Mitglied")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        case_id = self.record(interaction, member, "warn", reason)
        try:
            await member.send(
                f"Du wurdest auf **{interaction.guild.name}** verwarnt.\nGrund: {reason}"
            )
        except discord.HTTPException:
            pass
        await self.respond(interaction, case_id, f"{member.mention} wurde verwarnt.")

    @app_commands.command(name="warnings", description="Zeigt aktive Verwarnungen")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(ModerationCase)
                    .where(
                        ModerationCase.guild_id == str(interaction.guild_id),
                        ModerationCase.user_id == str(member.id),
                        ModerationCase.action == "warn",
                        ModerationCase.status == "active",
                    )
                    .order_by(ModerationCase.id.desc())
                    .limit(15)
                )
            )
        if not rows:
            text = "Keine aktiven Verwarnungen."
        else:
            text = "\n".join(f"`#{row.id}` {row.reason[:120]}" for row in rows)
        await interaction.response.send_message(
            f"**Verwarnungen für {member.display_name}**\n{text}", ephemeral=True
        )

    @app_commands.command(name="unwarn", description="Hebt eine Verwarnung auf")
    @app_commands.default_permissions(moderate_members=True)
    async def unwarn(self, interaction: discord.Interaction, case_number: int) -> None:
        with session_scope() as db:
            row = db.get(ModerationCase, case_number)
            if (
                not row
                or row.guild_id != str(interaction.guild_id)
                or row.action != "warn"
                or row.status != "active"
            ):
                await interaction.response.send_message(
                    "Aktive Verwarnung nicht gefunden.", ephemeral=True
                )
                return
            row.status = "revoked"
            row.revoked_at = datetime.now(timezone.utc)
            row.revoked_by = str(interaction.user.id)
        await interaction.response.send_message(
            f"Verwarnung **#{case_number}** wurde aufgehoben."
        )

    @app_commands.command(name="timeout", description="Gibt einem Mitglied Timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str,
    ) -> None:
        try:
            delta = parse_duration(duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await member.timeout(delta, reason=f"{interaction.user}: {reason}")
        case_id = self.record(interaction, member, "timeout", reason, delta)
        await self.respond(
            interaction, case_id, f"{member.mention} erhielt {duration} Timeout."
        )

    @app_commands.command(name="untimeout", description="Entfernt einen Timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def untimeout(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        await member.timeout(None, reason=f"{interaction.user}: {reason}")
        case_id = self.record(interaction, member, "untimeout", reason)
        await self.respond(interaction, case_id, f"Timeout von {member.mention} entfernt.")

    @app_commands.command(name="kick", description="Kickt ein Mitglied")
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        case_id = self.record(interaction, member, "kick", reason)
        await member.kick(reason=f"{interaction.user}: {reason}")
        await self.respond(interaction, case_id, f"{member} wurde gekickt.")

    @app_commands.command(name="ban", description="Bannt ein Mitglied")
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        delete_messages_hours: app_commands.Range[int, 0, 168] = 0,
    ) -> None:
        case_id = self.record(interaction, user, "ban", reason)
        await interaction.guild.ban(
            user,
            reason=f"{interaction.user}: {reason}",
            delete_message_seconds=delete_messages_hours * 3600,
        )
        await self.respond(interaction, case_id, f"{user} wurde gebannt.")

    @app_commands.command(name="tempban", description="Bannt einen Benutzer temporär")
    @app_commands.default_permissions(ban_members=True)
    async def tempban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        duration: str,
        reason: str,
    ) -> None:
        try:
            delta = parse_duration(duration)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        case_id = self.record(interaction, user, "tempban", reason, delta)
        await interaction.guild.ban(user, reason=f"{interaction.user}: {reason}")
        await self.respond(interaction, case_id, f"{user} wurde für {duration} gebannt.")

    @tasks.loop(minutes=1)
    async def expire_tempbans(self) -> None:
        now = datetime.now(timezone.utc)
        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(ModerationCase).where(
                        ModerationCase.action == "tempban",
                        ModerationCase.status == "active",
                    )
                )
            )
            due: list[tuple[int, int, int]] = []
            for row in rows:
                created = row.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created + timedelta(minutes=row.duration_minutes or 0) <= now:
                    due.append((row.id, int(row.guild_id), int(row.user_id)))
        for case_id, guild_id, user_id in due:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            try:
                await guild.unban(discord.Object(user_id), reason=f"Tempban #{case_id} abgelaufen")
            except (discord.NotFound, discord.Forbidden):
                pass
            with session_scope() as db:
                row = db.get(ModerationCase, case_id)
                if row:
                    row.status = "expired"

    @expire_tempbans.before_loop
    async def before_expiry(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="unban", description="Entbannt einen Benutzer")
    @app_commands.default_permissions(ban_members=True)
    async def unban(
        self, interaction: discord.Interaction, user_id: str, reason: str
    ) -> None:
        if not user_id.isdigit():
            await interaction.response.send_message(
                "Die Discord-ID ist ungültig.", ephemeral=True
            )
            return
        user = discord.Object(int(user_id))
        await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")
        case_id = self.record(interaction, user, "unban", reason)
        await self.respond(interaction, case_id, f"Benutzer {user_id} wurde entbannt.")

    @app_commands.command(name="clear", description="Löscht Nachrichten")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Nur in Textkanälen verfügbar.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(
            f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True
        )

    @app_commands.command(name="slowmode", description="Setzt den Slowmode")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
    ) -> None:
        await interaction.channel.edit(
            slowmode_delay=seconds, reason=f"Geändert von {interaction.user}"
        )
        await interaction.response.send_message(f"Slowmode: **{seconds} Sekunden**.")

    @app_commands.command(name="lock", description="Sperrt den aktuellen Kanal")
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction) -> None:
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            send_messages=False,
            reason=f"Gesperrt von {interaction.user}",
        )
        await interaction.response.send_message("🔒 Kanal gesperrt.")

    @app_commands.command(name="unlock", description="Entsperrt den aktuellen Kanal")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            send_messages=None,
            reason=f"Entsperrt von {interaction.user}",
        )
        await interaction.response.send_message("🔓 Kanal entsperrt.")

    @app_commands.command(name="nickname", description="Ändert den Nickname")
    @app_commands.default_permissions(manage_nicknames=True)
    async def nickname(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        nickname: str | None = None,
    ) -> None:
        await member.edit(nick=nickname, reason=f"Geändert von {interaction.user}")
        await interaction.response.send_message(
            f"Nickname von {member.mention} wurde geändert."
        )

    @role.command(name="add", description="Fügt einem Mitglied eine Rolle hinzu")
    @app_commands.default_permissions(manage_roles=True)
    async def role_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: discord.Role,
    ) -> None:
        if role.managed or role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Diese Rolle kann ich nicht vergeben.", ephemeral=True
            )
            return
        await member.add_roles(role, reason=f"Vergeben von {interaction.user}")
        await interaction.response.send_message(
            f"{role.mention} wurde {member.mention} hinzugefügt."
        )

    @role.command(name="remove", description="Entfernt eine Rolle")
    @app_commands.default_permissions(manage_roles=True)
    async def role_remove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: discord.Role,
    ) -> None:
        if role.managed or role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Diese Rolle kann ich nicht entfernen.", ephemeral=True
            )
            return
        await member.remove_roles(role, reason=f"Entfernt von {interaction.user}")
        await interaction.response.send_message(
            f"{role.mention} wurde {member.mention} entfernt."
        )

    @app_commands.command(name="case", description="Zeigt einen Moderationsfall")
    @app_commands.default_permissions(moderate_members=True)
    async def case(self, interaction: discord.Interaction, case_number: int) -> None:
        with session_scope() as db:
            row = db.get(ModerationCase, case_number)
            if not row or row.guild_id != str(interaction.guild_id):
                await interaction.response.send_message(
                    "Fall nicht gefunden.", ephemeral=True
                )
                return
            embed = discord.Embed(
                title=f"Moderationsfall #{row.id}",
                description=row.reason,
                color=0x7C5CFF,
                timestamp=row.created_at,
            )
            embed.add_field(name="Aktion", value=row.action)
            embed.add_field(name="Status", value=row.status)
            embed.add_field(name="Benutzer", value=f"{row.user_name} (`{row.user_id}`)")
            embed.add_field(name="Moderator", value=row.moderator_name)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
