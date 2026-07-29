"""Welcome and farewell events driven entirely by dashboard settings."""

from __future__ import annotations

import discord
from discord.ext import commands

from database.manager import get_setting


def render(template: str, member: discord.Member) -> str:
    values = {
        "user": member.name,
        "username": member.name,
        "display_name": member.display_name,
        "mention": member.mention,
        "server": member.guild.name,
        "member_count": member.guild.member_count or 0,
        "created_at": discord.utils.format_dt(member.created_at, "D"),
        "joined_at": discord.utils.format_dt(member.joined_at, "D")
        if member.joined_at
        else "–",
    }
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        config = get_setting(str(member.guild.id), "welcome", {})
        if not config.get("enabled"):
            return
        role_ids = list(config.get("role_ids", []))
        if config.get("welcome_role_id"):
            role_ids.append(config["welcome_role_id"])
        roles = [
            member.guild.get_role(int(role_id))
            for role_id in dict.fromkeys(role_ids)
            if role_id
        ]
        roles = [role for role in roles if role and not role.managed]
        if roles:
            try:
                await member.add_roles(*roles, reason="zyrahd Willkommensrollen")
            except discord.Forbidden:
                pass
        channel_id = config.get("channel_id")
        channel = member.guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            description = render(
                str(
                    config.get(
                        "description",
                        "Willkommen {mention} auf **{server}**! Du bist Mitglied #{member_count}.",
                    )
                ),
                member,
            )
            if config.get("mode", "embed") == "text":
                await channel.send(
                    description,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            else:
                color = int(str(config.get("color", "#7c5cff")).lstrip("#"), 16)
                embed = discord.Embed(
                    title=render(str(config.get("title", "Willkommen!")), member),
                    description=description,
                    color=color,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                if config.get("image_url"):
                    embed.set_image(url=str(config["image_url"]))
                if config.get("footer"):
                    embed.set_footer(text=render(str(config["footer"]), member))
                await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
        if config.get("dm_message"):
            try:
                await member.send(render(str(config["dm_message"]), member))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        config = get_setting(str(member.guild.id), "farewell", {})
        if not config.get("enabled"):
            return
        channel_id = config.get("channel_id")
        channel = member.guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        text = render(
            str(config.get("description", "{display_name} hat {server} verlassen.")),
            member,
        )
        if config.get("mode", "embed") == "text":
            await channel.send(text)
            return
        embed = discord.Embed(
            title=render(str(config.get("title", "Auf Wiedersehen")), member),
            description=text,
            color=int(str(config.get("color", "#786f91")).lstrip("#"), 16),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
