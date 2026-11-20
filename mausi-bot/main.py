"""Mausi ji: the house bot for mera mirchidaar bhosada.

Run:  python main.py   (reads DISCORD_TOKEN and GUILD_ID from .env)
"""
from __future__ import annotations

import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from bot.storage import Store
from bot.util import NotAllowed, TIER_LABEL

EXTENSIONS = [
    "bot.cogs.welcome",
    "bot.cogs.reaction_roles",
    "bot.cogs.moderation",
    "bot.cogs.setup",
    "bot.cogs.panel",
    "bot.cogs.autoreact",
    "bot.cogs.starboard",
    "bot.cogs.voicerooms",
    "bot.cogs.embeds",
    "bot.cogs.dashboard",
]

log = logging.getLogger("mausi")


class MausiBot(commands.Bot):
    def __init__(self, store: Store, guild_id: int | None = None) -> None:
        intents = discord.Intents.default()
        intents.members = True          # welcome messages and auto-roles
        intents.message_content = True  # keyword auto-reactions
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            activity=discord.Activity(type=discord.ActivityType.watching, name="darbar ki chugli"),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        self.store = store
        self.dev_guild_id = guild_id
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        if self.dev_guild_id:
            guild = discord.Object(id=self.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to server %s (instant)", len(synced), self.dev_guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (can take up to an hour to show)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s). Mausi ji aa gayi.", self.user, self.user.id)

    async def on_app_command_error(self, interaction: discord.Interaction,
                                   error: app_commands.AppCommandError) -> None:
        if isinstance(error, NotAllowed):
            text = f"Yeh command sirf **{TIER_LABEL[error.needed]}** (ya upar) ke liye hai, behen."
        elif isinstance(error, app_commands.NoPrivateMessage):
            text = "Yeh command server mein chala, DM mein nahi."
        elif isinstance(error, app_commands.CheckFailure):
            text = "Tujhe yeh karne ki permission nahi hai."
        else:
            log.exception("Command failed", exc_info=error)
            text = "Kuch gadbad ho gayi. Logs check kar."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN missing. Copy .env.example to .env and paste your bot token there.")
    guild_id = os.getenv("GUILD_ID")
    store = Store(os.getenv("DATA_PATH", "data.json"))
    bot = MausiBot(store, int(guild_id) if guild_id else None)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
