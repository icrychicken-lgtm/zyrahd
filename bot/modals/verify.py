"""Einfaches Verify-Captcha Modal."""

from __future__ import annotations

import random

import discord

from database.manager import get_session
from database.models import VerifyConfig
from bot.utils.audit import write_activity
from bot.utils.helpers import parse_color
from datetime import datetime, timezone


class VerifyCaptchaModal(discord.ui.Modal, title="Verifizierungs-Captcha"):
    def __init__(self):
        super().__init__()
        a, b = random.randint(2, 9), random.randint(1, 9)
        self.expected = a + b
        self.answer = discord.ui.TextInput(
            label=f"Was ist {a} + {b}?",
            placeholder="Ergebnis eingeben",
            required=True,
            max_length=4,
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = int(self.answer.value.strip())
        except ValueError:
            await interaction.response.send_message("Ungültige Antwort.", ephemeral=True)
            return
        if value != self.expected:
            await interaction.response.send_message("Falsche Antwort. Versuche es erneut.", ephemeral=True)
            return

        with get_session() as session:
            cfg = session.query(VerifyConfig).first()
            if not cfg or not cfg.verified_role_id:
                await interaction.response.send_message("Verifizierung nicht konfiguriert.", ephemeral=True)
                return
            role_id = cfg.verified_role_id
            remove_ids = cfg.get_remove_roles()
            dm_enabled = cfg.dm_enabled
            dm_message = cfg.dm_message
            log_channel_id = cfg.log_channel_id

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur Servermitglieder.", ephemeral=True)
            return

        role = interaction.guild.get_role(role_id) if interaction.guild else None
        if not role:
            await interaction.response.send_message("Rolle nicht gefunden.", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason="Verifizierung (Captcha)")
            for rid in remove_ids:
                r = interaction.guild.get_role(rid)
                if r and r in member.roles:
                    await member.remove_roles(r, reason="Verifizierung")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return

        await interaction.response.send_message("Erfolgreich verifiziert!", ephemeral=True)
        write_activity("verify", f"{member} wurde verifiziert (Captcha).")

        if dm_enabled and dm_message:
            try:
                await member.send(dm_message)
            except discord.HTTPException:
                pass

        if log_channel_id and interaction.guild:
            ch = interaction.guild.get_channel(log_channel_id)
            if isinstance(ch, discord.TextChannel):
                embed = discord.Embed(
                    title="Verifizierung",
                    description=f"{member.mention} (Captcha)",
                    color=parse_color("#9B5CFF"),
                    timestamp=datetime.now(timezone.utc),
                )
                await ch.send(embed=embed)
