"""Verify-Button View."""

from __future__ import annotations

from datetime import datetime, timezone

import discord

from database.manager import get_session
from database.models import VerifyConfig
from bot.utils.helpers import parse_color
from bot.utils.audit import write_activity


class VerifyView(discord.ui.View):
    def __init__(self, button_label: str = "✅ Verifizieren"):
        super().__init__(timeout=None)
        self.add_item(VerifyButton(button_label))


class VerifyButton(discord.ui.Button):
    def __init__(self, label: str = "✅ Verifizieren"):
        super().__init__(
            label=label[:80],
            style=discord.ButtonStyle.success,
            custom_id="zyrahd:verify:button",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        with get_session() as session:
            cfg = session.query(VerifyConfig).first()
            if not cfg or not cfg.enabled or not cfg.verified_role_id:
                await interaction.response.send_message(
                    "Verifizierung ist derzeit nicht verfügbar.", ephemeral=True
                )
                return
            role_id = cfg.verified_role_id
            remove_ids = cfg.get_remove_roles()
            min_age = cfg.min_account_age_days
            dm_enabled = cfg.dm_enabled
            dm_message = cfg.dm_message
            log_channel_id = cfg.log_channel_id
            captcha = cfg.captcha_enabled

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Nur Servermitglieder können sich verifizieren.", ephemeral=True
            )
            return

        if min_age > 0:
            age_days = (datetime.now(timezone.utc) - member.created_at.replace(tzinfo=timezone.utc)).days
            if age_days < min_age:
                await interaction.response.send_message(
                    f"Dein Account muss mindestens {min_age} Tage alt sein.",
                    ephemeral=True,
                )
                return

        if captcha:
            # Einfaches Captcha über Modal
            from bot.modals.verify import VerifyCaptchaModal

            await interaction.response.send_modal(VerifyCaptchaModal())
            return

        role = interaction.guild.get_role(role_id) if interaction.guild else None
        if not role:
            await interaction.response.send_message(
                "Verifizierungsrolle wurde nicht gefunden.", ephemeral=True
            )
            return

        try:
            await member.add_roles(role, reason="Verifizierung")
            for rid in remove_ids:
                r = interaction.guild.get_role(rid)
                if r and r in member.roles:
                    await member.remove_roles(r, reason="Verifizierung")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)
            return

        await interaction.response.send_message(
            "Du wurdest erfolgreich verifiziert!", ephemeral=True
        )
        write_activity("verify", f"{member} wurde verifiziert.")

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
                    description=f"{member.mention} wurde verifiziert.",
                    color=parse_color("#9B5CFF"),
                    timestamp=datetime.now(timezone.utc),
                )
                await ch.send(embed=embed)
