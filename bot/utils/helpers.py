"""Allgemeine Hilfsfunktionen."""

from __future__ import annotations

import colorsys
import re
from datetime import datetime
from typing import Any, Optional

import discord
import pytz

import config


def tz_now() -> datetime:
    return datetime.now(pytz.timezone(config.TIMEZONE))


def parse_color(value: str, default: int = 0x9B5CFF) -> int:
    if not value:
        return default
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    try:
        return int(value, 16)
    except ValueError:
        return default


def color_to_hex(color: int) -> str:
    return f"#{color:06X}"


def replace_placeholders(text: str, mapping: dict[str, Any]) -> str:
    if not text:
        return ""
    result = text
    for key, value in mapping.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def member_placeholders(member: discord.Member) -> dict[str, Any]:
    created = member.created_at.astimezone(pytz.timezone(config.TIMEZONE))
    joined = (
        member.joined_at.astimezone(pytz.timezone(config.TIMEZONE))
        if member.joined_at
        else tz_now()
    )
    return {
        "user": str(member),
        "username": member.name,
        "display_name": member.display_name,
        "mention": member.mention,
        "server": member.guild.name if member.guild else "",
        "member_count": member.guild.member_count if member.guild else 0,
        "created_at": created.strftime("%d.%m.%Y %H:%M"),
        "joined_at": joined.strftime("%d.%m.%Y %H:%M"),
    }


def build_embed_from_dict(data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=data.get("title") or None,
        description=data.get("description") or None,
        color=parse_color(data.get("color", "#9B5CFF")),
        url=data.get("url") or None,
    )
    if data.get("author"):
        author = data["author"]
        embed.set_author(
            name=author.get("name", ""),
            url=author.get("url") or None,
            icon_url=author.get("icon_url") or None,
        )
    if data.get("footer"):
        footer = data["footer"]
        if isinstance(footer, str):
            embed.set_footer(text=footer)
        else:
            embed.set_footer(text=footer.get("text", ""), icon_url=footer.get("icon_url") or None)
    if data.get("thumbnail"):
        embed.set_thumbnail(url=data["thumbnail"])
    if data.get("image"):
        embed.set_image(url=data["image"])
    if data.get("timestamp"):
        embed.timestamp = datetime.utcnow()
    for field in data.get("fields") or []:
        embed.add_field(
            name=field.get("name", "\u200b"),
            value=field.get("value", "\u200b"),
            inline=bool(field.get("inline", False)),
        )
    return embed


def normalize_text_for_filter(text: str) -> str:
    """Entfernt einfache Umgehungsversuche (Leerzeichen/Sonderzeichen zwischen Buchstaben)."""
    text = text.lower()
    # Ersetze häufige Lookalikes
    replacements = str.maketrans(
        {
            "0": "o",
            "1": "i",
            "3": "e",
            "4": "a",
            "5": "s",
            "7": "t",
            "@": "a",
            "$": "s",
        }
    )
    text = text.translate(replacements)
    # Entferne Zeichen zwischen Buchstaben, behalte Wortgrenzen
    cleaned = re.sub(r"[^a-z0-9äöüß\s]", "", text)
    collapsed = re.sub(r"(?<=\w)\s+(?=\w)", "", cleaned)
    return collapsed


INVITE_REGEX = re.compile(
    r"(discord\.gg/|discord\.com/invite/|discordapp\.com/invite/)[a-zA-Z0-9-]+",
    re.IGNORECASE,
)
URL_REGEX = re.compile(r"https?://|www\.", re.IGNORECASE)


def contains_invite(text: str) -> bool:
    return bool(INVITE_REGEX.search(text or ""))


def contains_url(text: str) -> bool:
    return bool(URL_REGEX.search(text or ""))


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not parts:
        parts.append(f"{secs}s")
    return " ".join(parts) or "0s"


def accent_gradient(seed: int = 0) -> str:
    hue = (0.75 + (seed % 20) * 0.01) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 1.0)
    return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
