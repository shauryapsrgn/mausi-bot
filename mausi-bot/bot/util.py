"""Shared helpers: permission tiers, templates, durations, emoji keys, logging."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

if TYPE_CHECKING:
    from main import MausiBot

# ---------------------------------------------------------------- tiers
TIER_NAMES = ["helper", "mod", "admin"]
TIER_LEVEL = {"none": 0, "helper": 1, "mod": 2, "admin": 3}
TIER_LABEL = {
    "helper": "rishwatkhor munshi (helpers)",
    "mod": "lathi-charge wali aunty (mods)",
    "admin": "co-admins",
}


def member_level(member: discord.Member, conf: dict) -> int:
    """0 = nobody, 1 = helper, 2 = mod, 3 = admin."""
    if member.guild.owner_id == member.id or member.guild_permissions.administrator:
        return 3
    role_ids = {r.id for r in member.roles}
    level = 0
    for name in TIER_NAMES:
        if role_ids & set(conf["tiers"].get(name, [])):
            level = max(level, TIER_LEVEL[name])
    return level


class NotAllowed(app_commands.CheckFailure):
    def __init__(self, needed: str) -> None:
        super().__init__(needed)
        self.needed = needed


def require_tier(tier: str):
    """Slash-command check: caller must be at least this tier."""
    needed = TIER_LEVEL[tier]

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        conf = interaction.client.store.guild(interaction.guild.id)  # type: ignore[attr-defined]
        if member_level(interaction.user, conf) >= needed:
            return True
        raise NotAllowed(tier)

    return app_commands.check(predicate)


# Which tier each locked command needs by default. Change any of these from the
# dashboard's "Command access" page (saved in data.json as command_access).
COMMAND_ACCESS_DEFAULTS = {
    "warn": "helper",
    "warnings": "helper",
    "timeout": "helper",
    "untimeout": "helper",
    "clearwarnings": "mod",
    "kick": "mod",
    "ban": "mod",
    "unban": "mod",
    "purge": "mod",
    "slowmode": "mod",
    "lock": "mod",
    "embed": "mod",
}
COMMAND_ACCESS_LABELS = {
    "warn": "/warn", "warnings": "/warnings", "timeout": "/timeout", "untimeout": "/untimeout",
    "clearwarnings": "/clearwarnings", "kick": "/kick", "ban": "/ban", "unban": "/unban",
    "purge": "/purge", "slowmode": "/slowmode", "lock": "/lock and /unlock", "embed": "/embed (make and edit embeds)",
}


def access_tier(conf: dict, command: str) -> str:
    tier = conf.get("command_access", {}).get(command) or COMMAND_ACCESS_DEFAULTS[command]
    return tier if tier in TIER_LEVEL and tier != "none" else COMMAND_ACCESS_DEFAULTS[command]


def require_access(command: str):
    """Slash-command check using the per-command tier the server has chosen."""
    if command not in COMMAND_ACCESS_DEFAULTS:
        raise ValueError(command)

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        conf = interaction.client.store.guild(interaction.guild.id)  # type: ignore[attr-defined]
        tier = access_tier(conf, command)
        if member_level(interaction.user, conf) >= TIER_LEVEL[tier]:
            return True
        raise NotAllowed(tier)

    return app_commands.check(predicate)


def hierarchy_problem(actor: discord.Member, target: discord.Member) -> Optional[str]:
    """Return a reason the actor (or the bot) can't act on target, or None if fine."""
    guild = actor.guild
    if target.id == guild.owner_id:
        return "Rajmata pe haath? Server owner pe yeh nahi chalega."
    if target.id == actor.id:
        return "Khud pe? Itna bhi drama mat kar."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "Yeh banda tere barabar ya tujhse upar ke role mein hai."
    me = guild.me
    if target.top_role >= me.top_role:
        return "Mera role is bande se neeche hai. Server Settings > Roles mein mera role upar khiskao."
    return None


# ---------------------------------------------------------------- templates
_CHANNEL_RE = re.compile(r"\{#([^{}]+)\}")


def render(template: str, member: discord.Member) -> str:
    """Fill in {user} {name} {server} {count} and {#channel-name} placeholders."""
    guild = member.guild

    def channel_sub(match: re.Match) -> str:
        name = match.group(1).strip().lstrip("#")
        channel = discord.utils.get(guild.channels, name=name)
        return channel.mention if channel else f"#{name}"

    text = _CHANNEL_RE.sub(channel_sub, template)
    return (
        text.replace("{user}", member.mention)
        .replace("{name}", member.display_name)
        .replace("{server}", guild.name)
        .replace("{count}", str(guild.member_count or len(guild.members)))
    )


# ---------------------------------------------------------------- durations
_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> Optional[timedelta]:
    """'10m', '2h30m', '1d', '1w' -> timedelta. Returns None if unreadable."""
    text = text.strip().lower().replace(" ", "")
    if not text:
        return None
    pos, total = 0, 0
    for match in _DURATION_RE.finditer(text):
        if match.start() != pos:
            return None
        total += int(match.group(1)) * _UNIT[match.group(2)]
        pos = match.end()
    if pos != len(text) or total <= 0:
        return None
    return timedelta(seconds=total)


def human_duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            parts.append(f"{seconds // size}{unit}")
            seconds %= size
    return " ".join(parts) or "0s"


# ---------------------------------------------------------------- emoji
def emoji_key(emoji: str | discord.PartialEmoji | discord.Emoji) -> str:
    """Normalise an emoji so reactions and saved settings always match."""
    if isinstance(emoji, (discord.PartialEmoji, discord.Emoji)):
        if getattr(emoji, "id", None):
            return f"custom:{emoji.id}"
        return str(emoji.name).replace("️", "")
    text = str(emoji).strip()
    partial = discord.PartialEmoji.from_str(text)
    if partial.id:
        return f"custom:{partial.id}"
    return text.replace("️", "")


# ---------------------------------------------------------------- mod log
async def send_log(bot: "MausiBot", guild: discord.Guild, embed: discord.Embed) -> None:
    conf = bot.store.guild(guild.id)
    channel_id = conf.get("log_channel_id")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


PINK = discord.Colour.from_rgb(233, 30, 99)
