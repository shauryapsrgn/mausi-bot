"""Actions shared by slash commands and the web dashboard."""
from __future__ import annotations

import json
import os
from typing import Optional

import discord

from bot.util import PINK, emoji_key

PRESETS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "presets.json")
BOTTOM_ROLE = "abhi tak shareef"


def load_presets() -> dict:
    with open(PRESETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def plan_role_order(movable_top_down: list, order_names: list[str]) -> list:
    """Return the new top-to-bottom order: listed roles first (in list order),
    then everything else in its current order, keeping the BOTTOM_ROLE last."""
    by_name = {}
    for role in movable_top_down:
        by_name.setdefault(role.name, role)
    desired = [by_name[n] for n in order_names if n in by_name]
    seen = {id(r) for r in desired}
    rest = [r for r in movable_top_down if id(r) not in seen]
    if desired and desired[-1].name == BOTTOM_ROLE:
        return desired[:-1] + rest + [desired[-1]]
    return desired + rest


async def sort_roles(guild: discord.Guild, order_names: list[str]) -> tuple[int, list[str]]:
    """Reorder every role below the bot's own role. Returns (roles placed, names not found)."""
    me = guild.me
    movable = [r for r in guild.roles if r < me.top_role and not r.is_default() and not r.managed]
    current = sorted(movable, key=lambda r: r.position, reverse=True)
    final = plan_role_order(current, order_names)
    top = me.top_role.position - 1
    positions = {role: top - i for i, role in enumerate(final)}
    await guild.edit_role_positions(positions=positions, reason="Mausi ji: sort roles")
    missing = [n for n in order_names if not discord.utils.get(guild.roles, name=n)]
    return len(final), missing


class EmbedError(ValueError):
    pass


def _url(value: str, label: str) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    if not value.startswith(("https://", "http://")):
        raise EmbedError(f"{label} must be a link starting with https://")
    return value


def build_embed(data: dict) -> discord.Embed:
    """Turn embed-maker form data into a discord.Embed, checking Discord's limits."""
    title = (data.get("title") or "").strip()[:256] or None
    description = (data.get("description") or "").strip()[:4096] or None
    colour_text = (data.get("color") or "").strip()
    try:
        colour = discord.Colour.from_str(colour_text) if colour_text else PINK
    except ValueError:
        raise EmbedError("Colour must look like #ff3d8b")
    embed = discord.Embed(title=title, description=description, colour=colour, url=_url(data.get("url"), "Title link"))
    if data.get("author"):
        embed.set_author(name=str(data["author"])[:256], icon_url=_url(data.get("author_icon"), "Author icon"))
    if data.get("footer"):
        embed.set_footer(text=str(data["footer"])[:2048])
    image = _url(data.get("image"), "Image")
    if image:
        embed.set_image(url=image)
    thumb = _url(data.get("thumbnail"), "Thumbnail")
    if thumb:
        embed.set_thumbnail(url=thumb)
    if data.get("timestamp"):
        embed.timestamp = discord.utils.utcnow()
    for field in (data.get("fields") or [])[:25]:
        name, value = (field.get("name") or "").strip(), (field.get("value") or "").strip()
        if name and value:
            embed.add_field(name=name[:256], value=value[:1024], inline=bool(field.get("inline")))
    if not (title or description or embed.fields or image):
        raise EmbedError("Give the embed at least a title, some text, a field or an image.")
    if len(embed) > 6000:
        raise EmbedError("Too much text: Discord allows 6000 characters per embed.")
    return embed


def embed_to_data(embed: discord.Embed) -> dict:
    return {
        "title": embed.title or "", "description": embed.description or "", "url": embed.url or "",
        "color": str(embed.colour) if embed.colour else "", "author": embed.author.name or "",
        "author_icon": embed.author.icon_url or "", "footer": embed.footer.text or "",
        "image": embed.image.url or "", "thumbnail": embed.thumbnail.url or "",
        "timestamp": bool(embed.timestamp),
        "fields": [{"name": f.name, "value": f.value, "inline": f.inline} for f in embed.fields],
    }


def parse_message_link(link: str) -> Optional[tuple[int, int]]:
    """'https://discord.com/channels/g/c/m' -> (channel_id, message_id)."""
    parts = (link or "").strip().rstrip("/").split("/")
    if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
        return int(parts[-2]), int(parts[-1])
    return None


PLANNED_CHANNELS = [
    # (kind, name, category name, read_only)
    ("text", "mausi-ke-commands", "mohalla committee", False),
    ("text", "tareef-ki-deewar", "mohalla committee", True),
    ("text", "drag-ka-dangal", "mohalla committee", False),
    ("text", "sher-o-shayari", "mohalla committee", False),
    ("voice", "➕ naya kamra banao", "Voice channels", False),
]


async def ensure_channels(bot, guild: discord.Guild) -> list[str]:
    """Create the planned channels that don't exist yet, and wire them into settings."""
    made = []
    for kind, name, cat_name, read_only in PLANNED_CHANNELS:
        existing = discord.utils.get(guild.channels, name=name)
        category = discord.utils.get(guild.categories, name=cat_name)
        if existing is None:
            overwrites = {}
            if read_only:
                overwrites = {guild.default_role: discord.PermissionOverwrite(send_messages=False, add_reactions=True),
                              guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True)}
            if kind == "text":
                existing = await guild.create_text_channel(name, category=category, overwrites=overwrites,
                                                           reason="Mausi ji setup")
            else:
                existing = await guild.create_voice_channel(name, category=category, reason="Mausi ji setup")
            made.append(name)
    conf = bot.store.guild(guild.id)
    stars = discord.utils.get(guild.text_channels, name="tareef-ki-deewar")
    if stars and not conf["starboard"]["channel_id"]:
        conf["starboard"]["channel_id"] = stars.id
    lobby = discord.utils.get(guild.voice_channels, name="➕ naya kamra banao")
    if lobby and not conf["voicerooms"]["lobby_channel_id"]:
        conf["voicerooms"]["lobby_channel_id"] = lobby.id
    await bot.store.save()
    return made


def panel_embed(title: str, description: str, lines: list[str], exclusive: bool) -> discord.Embed:
    body = description + "\n\n" + "\n".join(lines)
    body += ("\n\n*Sirf ek chuno. Naya react karoge toh purana hat jaayega.*" if exclusive
             else "\n\n*Jitne chahiye utne utha lo. Hatana ho toh reaction hata do.*")
    return discord.Embed(title=title, description=body, colour=PINK)


async def post_preset(bot, guild: discord.Guild, preset: str, channel: discord.TextChannel,
                      create_missing: bool = False) -> tuple[Optional[str], list[str]]:
    """Post a reaction-role panel from presets.json. Returns (jump url or None, problems)."""
    presets = load_presets()
    if preset not in presets:
        return None, [f"Preset '{preset}' presets.json mein nahi hai."]
    p = presets[preset]
    mapping, lines, problems = {}, [], []
    for item in p["roles"]:
        role = discord.utils.get(guild.roles, name=item["role"])
        if role is None and create_missing:
            try:
                colour = discord.Colour.from_str(item["color"]) if item.get("color") else discord.Colour.default()
                role = await guild.create_role(name=item["role"], colour=colour,
                                               permissions=discord.Permissions.none(),
                                               reason=f"Reaction-role preset {preset}")
            except (discord.HTTPException, ValueError):
                role = None
        if role is None:
            problems.append(f"Role nahi mila: {item['role']}")
            continue
        if role >= guild.me.top_role:
            problems.append(f"{role.name} mere role se upar hai, main ise de nahi paaungi")
            continue
        mapping[emoji_key(item["emoji"])] = role.id
        lines.append(f"{item['emoji']}  {role.mention}" + (f"  {item['note']}" if item.get("note") else ""))
    if not mapping:
        return None, problems or ["Ek bhi role kaam ka nahi mila."]

    exclusive = bool(p.get("exclusive", False))
    msg = await channel.send(embed=panel_embed(p["title"], p.get("description", ""), lines, exclusive),
                             allowed_mentions=discord.AllowedMentions.none())
    for item in p["roles"]:
        if emoji_key(item["emoji"]) in mapping:
            try:
                await msg.add_reaction(item["emoji"])
            except discord.HTTPException:
                problems.append(f"Emoji react nahi ho paaya: {item['emoji']}")
    conf = bot.store.guild(guild.id)
    conf["reaction_roles"][str(msg.id)] = {"channel_id": channel.id, "title": p["title"],
                                           "exclusive": exclusive, "mapping": mapping}
    await bot.store.save()
    return msg.jump_url, problems
