"""Server-Status-Überwachung (Minecraft/FiveM erweiterbar)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

import config
from bot.utils.helpers import parse_color
from database.manager import get_session
from database.models import ServerStatusConfig


class ServerStatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll.start()

    def cog_unload(self) -> None:
        self.poll.cancel()

    @tasks.loop(seconds=60)
    async def poll(self) -> None:
        if not self.bot.is_ready():
            return
        with get_session() as session:
            cfg = session.query(ServerStatusConfig).first()
            if not cfg or not cfg.enabled or not cfg.channel_id:
                return
            # Snapshot
            data = {
                "id": cfg.id,
                "channel_id": cfg.channel_id,
                "message_id": cfg.message_id,
                "server_name": cfg.server_name,
                "server_type": cfg.server_type,
                "endpoint": cfg.endpoint,
                "online_message": cfg.online_message,
                "offline_message": cfg.offline_message,
                "maintenance": cfg.maintenance,
                "interval": cfg.interval_seconds or 60,
            }

        status = await self._check(data)
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return
        channel = guild.get_channel(data["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        color = "#43B581" if status["online"] else "#F04747"
        if data["maintenance"]:
            color = "#FAA61A"
            desc = "🟡 Wartungsmodus"
        else:
            desc = data["online_message"] if status["online"] else data["offline_message"]

        embed = discord.Embed(
            title=f"Server-Status • {data['server_name'] or 'Server'}",
            description=desc,
            color=parse_color(color),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Spieler", value=f"{status['players']}/{status['max_players']}", inline=True)
        embed.add_field(name="Ping", value=f"{status['ping']} ms", inline=True)
        embed.add_field(name="Typ", value=data["server_type"], inline=True)
        embed.set_footer(text="zyrahd.net • Auto-Update")

        message_id = data["message_id"]
        try:
            if message_id:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed)
            else:
                msg = await channel.send(embed=embed)
                message_id = msg.id
        except discord.HTTPException:
            try:
                msg = await channel.send(embed=embed)
                message_id = msg.id
            except discord.HTTPException:
                return

        with get_session() as session:
            cfg = session.get(ServerStatusConfig, data["id"])
            if cfg:
                cfg.message_id = message_id
                cfg.last_status = "online" if status["online"] else "offline"
                cfg.last_players = status["players"]
                cfg.last_max_players = status["max_players"]
                cfg.last_ping = status["ping"]
                if status["online"]:
                    cfg.last_online = datetime.now(timezone.utc)

    async def _check(self, data: dict) -> dict:
        endpoint = (data.get("endpoint") or "").strip()
        result = {"online": False, "players": 0, "max_players": 0, "ping": 0}
        if not endpoint:
            return result
        # Minecraft: https://api.mcsrvstat.us/3/<host>
        # FiveM: http://ip:port/dynamic.json or info.json
        try:
            async with aiohttp.ClientSession() as session:
                url = endpoint
                if data["server_type"] == "minecraft" and not endpoint.startswith("http"):
                    url = f"https://api.mcsrvstat.us/3/{endpoint}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        return result
                    payload = await resp.json(content_type=None)
                    if data["server_type"] == "minecraft":
                        result["online"] = bool(payload.get("online"))
                        result["players"] = int((payload.get("players") or {}).get("online") or 0)
                        result["max_players"] = int((payload.get("players") or {}).get("max") or 0)
                    else:
                        # FiveM-like
                        result["online"] = True
                        result["players"] = int(payload.get("clients") or payload.get("players") or 0)
                        result["max_players"] = int(payload.get("sv_maxclients") or payload.get("maxPlayers") or 0)
                    result["ping"] = int(resp.headers.get("X-Response-Time", 0) or 0)
        except Exception:
            return result
        return result

    @poll.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerStatusCog(bot))
