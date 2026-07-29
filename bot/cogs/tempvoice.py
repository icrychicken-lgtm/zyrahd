"""Temporäre Sprachkanäle."""

from __future__ import annotations

import discord
from discord.ext import commands

import config
from database.manager import get_session
from database.models import TempVoiceChannel, TempVoiceConfig


class TempVoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.guild.id != config.GUILD_ID:
            return

        with get_session() as session:
            cfg = session.query(TempVoiceConfig).first()
            if not cfg or not cfg.enabled or not cfg.create_channel_id:
                return
            create_id = cfg.create_channel_id
            category_id = cfg.category_id
            name_format = cfg.name_format
            user_limit = cfg.user_limit

        # Join create channel -> create temp
        if after.channel and after.channel.id == create_id:
            category = member.guild.get_channel(category_id) if category_id else after.channel.category
            name = name_format.replace("{username}", member.display_name)[:90]
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(connect=True),
                member: discord.PermissionOverwrite(
                    manage_channels=True, connect=True, move_members=True
                ),
            }
            try:
                channel = await member.guild.create_voice_channel(
                    name=name,
                    category=category if isinstance(category, discord.CategoryChannel) else None,
                    overwrites=overwrites,
                    user_limit=user_limit or 0,
                    reason="Temp Voice",
                )
                await member.move_to(channel)
                with get_session() as session:
                    session.add(TempVoiceChannel(channel_id=channel.id, owner_id=member.id))
            except discord.HTTPException:
                return

        # Leave empty temp channel -> delete
        if before.channel:
            with get_session() as session:
                temp = (
                    session.query(TempVoiceChannel)
                    .filter(TempVoiceChannel.channel_id == before.channel.id)
                    .first()
                )
                if temp and len(before.channel.members) == 0:
                    channel_id = temp.channel_id
                    session.delete(temp)
                    ch = member.guild.get_channel(channel_id)
                    if ch:
                        try:
                            await ch.delete(reason="Temp Voice leer")
                        except discord.HTTPException:
                            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TempVoiceCog(bot))
