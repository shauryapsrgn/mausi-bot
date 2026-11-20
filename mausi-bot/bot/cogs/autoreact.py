"""Keyword auto-reactions: someone says "slay", Mausi ji reacts 💅."""
from __future__ import annotations

import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.util import require_tier


def compile_trigger(word: str) -> re.Pattern:
    # Whole words only, so "ate" doesn't fire on "late" or "debate".
    return re.compile(r"(?<![\w])" + re.escape(word.lower()) + r"(?![\w])", re.IGNORECASE)


def matching_triggers(text: str, triggers: list[dict]) -> list[dict]:
    text = text.lower()
    return [t for t in triggers if t.get("word") and compile_trigger(t["word"]).search(text)]


class AutoReact(commands.Cog):
    autoreact = app_commands.Group(
        name="autoreact",
        description="Words Mausi ji reacts to",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot) -> None:
        self.bot = bot
        self._last: dict[tuple[int, str], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or not message.content:
            return
        conf = self.bot.store.guild(message.guild.id)["autoreact"]
        if not conf["enabled"]:
            return
        now = time.monotonic()
        for trig in matching_triggers(message.content, conf["triggers"])[:3]:
            key = (message.channel.id, trig["word"].lower())
            if now - self._last.get(key, 0) < conf["cooldown_seconds"]:
                continue
            self._last[key] = now
            for emoji in trig["emojis"][:3]:
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    pass

    @autoreact.command(name="add", description="React with emoji whenever someone says a word")
    @app_commands.describe(word="Word or phrase (whole words only)", emojis="One to three emoji, separated by spaces")
    @require_tier("admin")
    async def add(self, interaction: discord.Interaction, word: str, emojis: str) -> None:
        conf = self.bot.store.guild(interaction.guild.id)["autoreact"]
        word = word.strip().lower()
        emoji_list = emojis.split()[:3]
        if not word or not emoji_list:
            await interaction.response.send_message("Word aur emoji dono chahiye.", ephemeral=True)
            return
        conf["triggers"] = [t for t in conf["triggers"] if t["word"].lower() != word]
        conf["triggers"].append({"word": word, "emojis": emoji_list})
        await self.bot.store.save()
        await interaction.response.send_message(f"Ab jab bhi koi **{word}** bolega, main {' '.join(emoji_list)} karungi.",
                                                ephemeral=True)

    @autoreact.command(name="remove", description="Stop reacting to a word")
    @require_tier("admin")
    async def remove(self, interaction: discord.Interaction, word: str) -> None:
        conf = self.bot.store.guild(interaction.guild.id)["autoreact"]
        before = len(conf["triggers"])
        conf["triggers"] = [t for t in conf["triggers"] if t["word"].lower() != word.strip().lower()]
        await self.bot.store.save()
        await interaction.response.send_message("Hata diya." if len(conf["triggers"]) < before else "Yeh word list mein tha hi nahi.",
                                                ephemeral=True)

    @autoreact.command(name="list", description="See every trigger word")
    @require_tier("admin")
    async def list_triggers(self, interaction: discord.Interaction) -> None:
        conf = self.bot.store.guild(interaction.guild.id)["autoreact"]
        lines = [f"`{t['word']}` → {' '.join(t['emojis'])}" for t in conf["triggers"]] or ["*koi trigger nahi*"]
        status = "ON" if conf["enabled"] else "OFF"
        await interaction.response.send_message(f"Auto-react: **{status}**, cooldown {conf['cooldown_seconds']}s\n" + "\n".join(lines),
                                                ephemeral=True)

    @autoreact.command(name="toggle", description="Turn auto-reactions on or off")
    @require_tier("admin")
    async def toggle(self, interaction: discord.Interaction, on: bool) -> None:
        self.bot.store.guild(interaction.guild.id)["autoreact"]["enabled"] = on
        await self.bot.store.save()
        await interaction.response.send_message(f"Auto-react {'ON' if on else 'OFF'}.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(AutoReact(bot))
