"""Tiny JSON-file storage for per-server settings.

Everything lives in one file (data.json by default). Writes are atomic
(write to a temp file, then rename) so a crash never leaves half a file.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
from typing import Any

DEFAULT_WELCOME_MESSAGE = (
    "Aayi hai {user}! 💅 {server} mein swagat hai, tu member number {count} hai.\n\n"
    "Pehle {#samvidhaan} padh le, phir {#mata-ke-roles} mein apne roles utha, "
    "aur {#aao-baitho-intro-do} mein apna parichay de. "
    "Yahan sab apne pronouns ke saath, apni poori izzat ke saath hain. Darbar mein dil se swagat."
)

DEFAULT_DM_MESSAGE = (
    "Hello {name}! {server} join karne ke liye shukriya. "
    "Rules ek baar padh lena, aur kuch bhi problem ho toh mods ko ping kar dena."
)

DEFAULT_TRIGGERS = [
    {"word": "slay", "emojis": ["💅"]},
    {"word": "mother", "emojis": ["👑"]},
    {"word": "mata", "emojis": ["🙏"]},
    {"word": "chai", "emojis": ["☕"]},
    {"word": "chugli", "emojis": ["👀"]},
    {"word": "drama", "emojis": ["🍿"]},
    {"word": "aunty", "emojis": ["👵"]},
    {"word": "bhosada", "emojis": ["🌶️"]},
    {"word": "queen", "emojis": ["👸"]},
    {"word": "ate", "emojis": ["🍽️"]},
    {"word": "periodt", "emojis": ["💅"]},
    {"word": "happy birthday", "emojis": ["🎂", "🎉"]},
    {"word": "janamdin", "emojis": ["🎂"]},
    {"word": "pride", "emojis": ["🌈"]},
    {"word": "sharma ji", "emojis": ["🙄"]},
    {"word": "rishta", "emojis": ["💍"]},
]

DEFAULT_ROLE_ORDER = [
    "lathi-charge wali aunty", "rishwatkhor munshi",
    "rajmata ki queens", "vip (vahiyad ichadari panoti)", "bhosadavati",
    "gulabi chunni", "rani pink", "sindoor", "kesar", "haldi", "mehendi",
    "pista", "firozi", "neel", "jamuni", "chai", "chandi",
    "whatsapp university ki VC", "padosan ki CCTV", "rishte wali aunty ka nightmare",
    "teen baar zoom-in wala thappad", "mummy ka chappal launcher", "shaadi mein biryani chor",
    "uncle ka naagin dance", "sharma ji ke bete ki dushman", "nimbu-mirchi on the thar",
    "hijdavati ki hijdiyaan",
    "he/him (uncle mat bolna)", "she/her (didi mat bolna)", "they/them (beta mat bolna)",
    "any/all (jo marzi, bas izzat se)", "pronouns: puch le na", "seedha par samajhdaar (ally)",
    "abhi tak shareef",
]

DEFAULT_GUILD: dict[str, Any] = {
    "welcome": {
        "enabled": True,
        "channel_id": None,
        "message": DEFAULT_WELCOME_MESSAGE,
        "dm_enabled": False,
        "dm_message": DEFAULT_DM_MESSAGE,
        "autorole_ids": [],
        "goodbye_enabled": False,
        "goodbye_message": "{name} chali gayi. Darbar thoda sa kam bhosada ho gaya. 🥲",
    },
    # Role IDs allowed to use moderation commands, by tier.
    # helper < mod < admin. Anyone with Discord's Administrator permission
    # (and the server owner) always counts as admin.
    "tiers": {"helper": [], "mod": [], "admin": []},
    "log_channel_id": None,
    # Per-command tier overrides, e.g. {"embed": "admin"}. Empty = defaults in util.py.
    "command_access": {},
    # Saved embed drafts from the dashboard: name -> embed data
    "embed_templates": {},
    # message_id -> {"channel_id", "title", "exclusive", "mapping": {emoji_key: role_id}}
    "reaction_roles": {},
    # user_id -> [{"reason", "mod_id", "ts"}]
    "warnings": {},
    # Keyword auto-reactions: say a word, Mausi ji reacts.
    "autoreact": {
        "enabled": True,
        "cooldown_seconds": 20,  # per channel, per trigger, so chats don't drown in emoji
        "triggers": DEFAULT_TRIGGERS,
    },
    # Starboard: messages with enough of the emoji get reposted.
    "starboard": {
        "enabled": True,
        "channel_id": None,
        "emoji": "⭐",
        "threshold": 3,
        "posted": {},  # original message id -> starboard message id
    },
    # Join-to-create voice rooms.
    "voicerooms": {
        "enabled": True,
        "lobby_channel_id": None,
        "category_id": None,
        "name_template": "{name} ka kamra",
        "rooms": {},  # voice channel id -> owner id
    },
    # Top-to-bottom order used by /setup sortroles (role names; anything not
    # listed keeps its place below these). Only roles below the bot can move.
    "role_order": DEFAULT_ROLE_ORDER,
}


def _merge_defaults(target: dict, defaults: dict) -> None:
    """Fill in any keys missing from target (used after upgrades)."""
    for key, value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(target[key], dict) and key not in ("reaction_roles", "warnings"):
            _merge_defaults(target[key], value)


class Store:
    def __init__(self, path: str = "data.json") -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def guild(self, guild_id: int) -> dict[str, Any]:
        """Return the live settings dict for a server (created if new)."""
        key = str(guild_id)
        conf = self._data.setdefault(key, {})
        _merge_defaults(conf, DEFAULT_GUILD)
        return conf

    async def save(self) -> None:
        async with self._lock:
            directory = os.path.dirname(os.path.abspath(self.path))
            fd, tmp = tempfile.mkstemp(prefix=".data-", suffix=".json", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
