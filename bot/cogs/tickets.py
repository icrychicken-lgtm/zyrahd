"""Discord ticket creation and persistent ticket controls."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.manager import session_scope
from database.models import Ticket, TicketMessage, TicketType


def _safe_channel_name(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]", "-", value.lower().replace(" ", "-"))
    return re.sub(r"-+", "-", value).strip("-")[:50] or "ticket"


class TicketForm(discord.ui.Modal):
    def __init__(self, cog: "TicketCog", ticket_type: TicketType) -> None:
        super().__init__(title=ticket_type.name[:45], timeout=600)
        self.cog = cog
        self.ticket_type_id = ticket_type.id
        fields = ticket_type.fields[:5]
        if not fields:
            fields = [
                type(
                    "DefaultField",
                    (),
                    {
                        "id": 0,
                        "label": "Wie können wir dir helfen?",
                        "field_type": "long",
                        "placeholder": "Beschreibe dein Anliegen …",
                        "required": True,
                        "min_length": 5,
                        "max_length": 1000,
                    },
                )()
            ]
        self.inputs: list[tuple[int, discord.ui.TextInput]] = []
        for field in fields:
            text_input = discord.ui.TextInput(
                label=field.label[:45],
                placeholder=field.placeholder[:100] or None,
                required=field.required,
                min_length=max(0, field.min_length) or None,
                max_length=min(4000, max(1, field.max_length)),
                style=(
                    discord.TextStyle.paragraph
                    if field.field_type == "long"
                    else discord.TextStyle.short
                ),
            )
            self.inputs.append((field.id, text_input))
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        values = {str(field_id): item.value for field_id, item in self.inputs}
        try:
            ticket = await self.cog.create_ticket(
                interaction.user, self.ticket_type_id, values
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"Dein Ticket wurde erstellt: <#{ticket.channel_id}>", ephemeral=True
        )


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, cog: "TicketCog", ticket_types: list[TicketType]) -> None:
        self.cog = cog
        options = [
            discord.SelectOption(
                label=item.name[:100],
                description=item.description[:100] or None,
                emoji=item.emoji or "🎫",
                value=str(item.id),
            )
            for item in ticket_types[:25]
        ]
        super().__init__(
            placeholder="Wähle den passenden Bereich …",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        with session_scope() as session:
            ticket_type = session.scalar(
                select(TicketType)
                .options(selectinload(TicketType.fields))
                .where(TicketType.id == int(self.values[0]), TicketType.enabled.is_(True))
            )
        if not ticket_type:
            await interaction.response.send_message(
                "Diese Ticket-Art ist nicht mehr verfügbar.", ephemeral=True
            )
            return
        await interaction.response.send_modal(TicketForm(self.cog, ticket_type))


class TicketTypeView(discord.ui.View):
    def __init__(self, cog: "TicketCog", ticket_types: list[TicketType]) -> None:
        super().__init__(timeout=600)
        self.add_item(TicketTypeSelect(cog, ticket_types))


class TicketPanel(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ticket erstellen",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="zyrahd:ticket:create",
    )
    async def create(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        cog = interaction.client.get_cog("TicketCog")
        if not cog:
            await interaction.response.send_message(
                "Das Ticket-Modul ist momentan nicht verfügbar.", ephemeral=True
            )
            return
        await cog.show_ticket_types(interaction)


class TicketControls(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @staticmethod
    def _ticket(channel_id: int) -> Ticket | None:
        with session_scope() as session:
            return session.scalar(
                select(Ticket).where(Ticket.channel_id == str(channel_id))
            )

    @discord.ui.button(
        label="Übernehmen",
        emoji="🙋",
        style=discord.ButtonStyle.success,
        custom_id="zyrahd:ticket:claim",
    )
    async def claim(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not interaction.channel_id:
            return
        with session_scope() as session:
            ticket = session.scalar(
                select(Ticket).where(Ticket.channel_id == str(interaction.channel_id))
            )
            if not ticket or ticket.status == "closed":
                await interaction.response.send_message(
                    "Dieses Ticket ist bereits geschlossen.", ephemeral=True
                )
                return
            if ticket.claimed_by_id and ticket.claimed_by_id != str(interaction.user.id):
                await interaction.response.send_message(
                    f"Das Ticket wurde bereits von {ticket.claimed_by_name} übernommen.",
                    ephemeral=True,
                )
                return
            ticket.claimed_by_id = str(interaction.user.id)
            ticket.claimed_by_name = interaction.user.display_name
            ticket.status = "claimed"
            session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=str(interaction.user.id),
                    author_name=interaction.user.display_name,
                    content=f"{interaction.user.display_name} hat das Ticket übernommen.",
                    source="system",
                    system_event=True,
                )
            )
        await interaction.response.send_message(
            f"🙋 {interaction.user.mention} hat das Ticket übernommen."
        )

    @discord.ui.button(
        label="Schließen",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="zyrahd:ticket:close",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not interaction.channel_id:
            return
        with session_scope() as session:
            ticket = session.scalar(
                select(Ticket).where(Ticket.channel_id == str(interaction.channel_id))
            )
            if not ticket or ticket.status == "closed":
                await interaction.response.send_message(
                    "Dieses Ticket ist bereits geschlossen.", ephemeral=True
                )
                return
            ticket.status = "closed"
            ticket.closed_at = datetime.now(UTC)
            ticket.close_reason = "Über Discord geschlossen"
            session.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=str(interaction.user.id),
                    author_name=interaction.user.display_name,
                    content=f"{interaction.user.display_name} hat das Ticket geschlossen.",
                    source="system",
                    system_event=True,
                )
            )
        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.set_permissions(
                interaction.user, send_messages=False
            )
            await interaction.channel.edit(name=f"closed-{interaction.channel.name}"[:100])
        await interaction.response.send_message(
            f"🔒 Ticket geschlossen von {interaction.user.mention}."
        )

    @discord.ui.button(
        label="Transcript",
        emoji="📄",
        style=discord.ButtonStyle.secondary,
        custom_id="zyrahd:ticket:transcript",
    )
    async def transcript(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if not interaction.channel_id:
            return
        with session_scope() as session:
            ticket = session.scalar(
                select(Ticket)
                .options(selectinload(Ticket.messages))
                .where(Ticket.channel_id == str(interaction.channel_id))
            )
            if not ticket:
                await interaction.response.send_message(
                    "Ticket nicht gefunden.", ephemeral=True
                )
                return
            content = "\n".join(
                f"[{message.created_at:%d.%m.%Y %H:%M}] "
                f"{message.author_name}: {message.content}"
                for message in ticket.messages
            )
        file = discord.File(
            io.BytesIO(content.encode("utf-8")),
            filename=f"ticket-{ticket.number}-transcript.txt",
        )
        await interaction.response.send_message(file=file, ephemeral=True)


class TicketCog(commands.Cog, name="TicketCog"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(TicketPanel())

    async def show_ticket_types(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "Tickets können nur auf dem Server erstellt werden.", ephemeral=True
            )
            return
        with session_scope() as session:
            ticket_types = list(
                session.scalars(
                    select(TicketType)
                    .where(
                        TicketType.guild_id == str(interaction.guild_id),
                        TicketType.enabled.is_(True),
                    )
                    .order_by(TicketType.position)
                )
            )
        if not ticket_types:
            await interaction.response.send_message(
                "Aktuell ist keine Ticket-Art aktiviert.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Wähle aus, worum es geht:",
            view=TicketTypeView(self, ticket_types),
            ephemeral=True,
        )

    @app_commands.command(name="ticket", description="Erstelle ein privates Support-Ticket")
    async def ticket(self, interaction: discord.Interaction) -> None:
        await self.show_ticket_types(interaction)

    async def create_ticket(
        self,
        member: discord.Member | discord.User,
        ticket_type_id: int,
        form_data: dict[str, str],
    ) -> Ticket:
        guild = self.bot.get_guild(getattr(member, "guild", None).id) if isinstance(member, discord.Member) else None
        if guild is None:
            guild = next(
                (item for item in self.bot.guilds if item.get_member(member.id)), None
            )
        if guild is None:
            raise ValueError("Du bist kein Mitglied des konfigurierten Servers.")

        with session_scope() as session:
            ticket_type = session.get(TicketType, ticket_type_id)
            if (
                not ticket_type
                or not ticket_type.enabled
                or ticket_type.guild_id != str(guild.id)
            ):
                raise ValueError("Diese Ticket-Art ist nicht verfügbar.")
            open_count = session.scalar(
                select(func.count(Ticket.id)).where(
                    Ticket.creator_id == str(member.id),
                    Ticket.ticket_type_id == ticket_type.id,
                    Ticket.status.in_(("open", "claimed", "waiting")),
                )
            )
            if (open_count or 0) >= ticket_type.max_open:
                raise ValueError(
                    f"Du darfst maximal {ticket_type.max_open} offene Tickets dieser Art haben."
                )
            latest = session.scalar(
                select(Ticket)
                .where(
                    Ticket.creator_id == str(member.id),
                    Ticket.ticket_type_id == ticket_type.id,
                )
                .order_by(Ticket.created_at.desc())
                .limit(1)
            )
            if latest and latest.created_at:
                created = latest.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if created > datetime.now(UTC) - timedelta(
                    minutes=ticket_type.cooldown_minutes
                ):
                    raise ValueError("Bitte warte noch, bevor du ein weiteres Ticket erstellst.")
            number = (
                session.scalar(
                    select(func.max(Ticket.number)).where(
                        Ticket.guild_id == str(guild.id)
                    )
                )
                or 0
            ) + 1
            category_id = ticket_type.category_id
            role_ids = json.loads(ticket_type.support_role_ids or "[]")
            welcome = ticket_type.welcome_message
            type_name = ticket_type.name
            type_color = ticket_type.color
            ticket = Ticket(
                guild_id=str(guild.id),
                number=number,
                ticket_type_id=ticket_type.id,
                creator_id=str(member.id),
                creator_name=member.display_name,
                form_data=json.dumps(form_data, ensure_ascii=False),
            )
            session.add(ticket)
            session.flush()
            ticket_id = ticket.id

        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }
        guild_member = guild.get_member(member.id)
        if guild_member:
            overwrites[guild_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        for role_id in role_ids:
            role = guild.get_role(int(role_id))
            if role and not role.is_default():
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )
        category = guild.get_channel(int(category_id)) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = None
        try:
            channel = await guild.create_text_channel(
                f"ticket-{number}-{_safe_channel_name(member.display_name)}",
                category=category,
                overwrites=overwrites,
                topic=f"Zyrahd Ticket #{number} | Nutzer {member.id}",
                reason=f"Ticket {type_name} erstellt",
            )
        except discord.HTTPException as exc:
            with session_scope() as session:
                failed_ticket = session.get(Ticket, ticket_id)
                if failed_ticket:
                    session.delete(failed_ticket)
            raise ValueError(
                "Der Ticket-Kanal konnte nicht erstellt werden. Prüfe die Bot-Rechte."
            ) from exc

        with session_scope() as session:
            saved = session.get(Ticket, ticket_id)
            saved.channel_id = str(channel.id)

        embed = discord.Embed(
            title=f"{type_name} · Ticket #{number}",
            description=welcome,
            color=discord.Color.from_str(type_color),
            timestamp=datetime.now(UTC),
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        for field_id, answer in form_data.items():
            with session_scope() as session:
                current_type = session.get(TicketType, ticket_type_id)
                field = next(
                    (item for item in current_type.fields if str(item.id) == field_id),
                    None,
                )
            embed.add_field(
                name=field.label if field else "Anliegen",
                value=answer[:1024] or "—",
                inline=False,
            )
        mentions = " ".join(f"<@&{role_id}>" for role_id in role_ids)
        await channel.send(
            content=f"{guild_member.mention if guild_member else member.mention} {mentions}".strip(),
            embed=embed,
            view=TicketControls(),
        )
        with session_scope() as session:
            return session.get(Ticket, ticket_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
