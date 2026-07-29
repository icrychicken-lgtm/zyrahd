"""Willkommens- und Abschiedssystem."""

from __future__ import annotations

import discord
from discord.ext import commands

import config
from bot.utils.helpers import build_embed_from_dict, member_placeholders, parse_color, replace_placeholders
from database.manager import get_session
from database.models import GoodbyeConfig, WelcomeConfig
from bot.utils.audit import write_activity


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != config.GUILD_ID:
            return

        with get_session() as session:
            cfg = session.query(WelcomeConfig).first()
            if not cfg or not cfg.enabled:
                return
            channel_id = cfg.channel_id
            use_embed = cfg.use_embed
            title = cfg.title
            description = cfg.description
            color = cfg.color
            thumbnail = cfg.thumbnail_url
            image = cfg.image_url
            footer = cfg.footer
            plain = cfg.plain_message
            role_ids = cfg.get_roles()
            dm_enabled = cfg.dm_enabled
            dm_message = cfg.dm_message

        mapping = member_placeholders(member)

        # Rollen
        for rid in role_ids:
            role = member.guild.get_role(rid)
            if role:
                try:
                    await member.add_roles(role, reason="Willkommensrolle")
                except discord.HTTPException:
                    pass

        channel = member.guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            if use_embed:
                embed = discord.Embed(
                    title=replace_placeholders(title, mapping),
                    description=replace_placeholders(description, mapping),
                    color=parse_color(color),
                )
                if thumbnail:
                    embed.set_thumbnail(url=thumbnail)
                else:
                    embed.set_thumbnail(url=member.display_avatar.url)
                if image:
                    embed.set_image(url=image)
                if footer:
                    embed.set_footer(text=replace_placeholders(footer, mapping))
                await channel.send(embed=embed)
            else:
                await channel.send(replace_placeholders(plain, mapping))

        if dm_enabled and dm_message:
            try:
                await member.send(replace_placeholders(dm_message, mapping))
            except discord.HTTPException:
                pass

        write_activity("member", f"{member} ist beigetreten.")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild.id != config.GUILD_ID:
            return

        with get_session() as session:
            cfg = session.query(GoodbyeConfig).first()
            if not cfg or not cfg.enabled:
                return
            channel_id = cfg.channel_id
            use_embed = cfg.use_embed
            title = cfg.title
            description = cfg.description
            color = cfg.color
            image = cfg.image_url
            plain = cfg.plain_message

        mapping = member_placeholders(member)
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return

        if use_embed:
            embed = discord.Embed(
                title=replace_placeholders(title, mapping),
                description=replace_placeholders(description, mapping),
                color=parse_color(color),
            )
            if image:
                embed.set_image(url=image)
            await channel.send(embed=embed)
        else:
            await channel.send(replace_placeholders(plain, mapping))

        write_activity("member", f"{member} hat den Server verlassen.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
