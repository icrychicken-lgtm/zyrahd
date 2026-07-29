"""Embed-Hilfen und Reaction Roles Listener."""

from __future__ import annotations

import json

import discord
from discord.ext import commands

import config
from database.manager import get_session
from database.models import ReactionRolePanel


class EmbedsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id") if interaction.data else None
        if not custom_id or not str(custom_id).startswith("zyrahd:rr:"):
            return
        # zyrahd:rr:{panel_id}:{role_id}
        parts = str(custom_id).split(":")
        if len(parts) < 4:
            return
        role_id = int(parts[3])
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("Rolle nicht gefunden.", ephemeral=True)
            return

        panel_id = int(parts[2])
        exclusive = False
        other_roles = []
        with get_session() as session:
            panel = session.get(ReactionRolePanel, panel_id)
            if panel:
                exclusive = panel.exclusive
                try:
                    roles = json.loads(panel.roles_json or "[]")
                except json.JSONDecodeError:
                    roles = []
                other_roles = [int(r.get("role_id")) for r in roles if r.get("role_id")]

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Reaction Role")
                await interaction.response.send_message(f"{role.mention} entfernt.", ephemeral=True)
            else:
                if exclusive:
                    to_remove = [interaction.guild.get_role(rid) for rid in other_roles if rid != role_id]
                    to_remove = [r for r in to_remove if r and r in member.roles]
                    if to_remove:
                        await member.remove_roles(*to_remove, reason="Exclusive Reaction Role")
                await member.add_roles(role, reason="Reaction Role")
                await interaction.response.send_message(f"{role.mention} erhalten.", ephemeral=True)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Fehler: {exc}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbedsCog(bot))
