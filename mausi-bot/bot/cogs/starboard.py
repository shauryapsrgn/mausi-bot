"""Starboard: enough ⭐ on a message and it gets framed in #tareef-ki-deewar."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.util import PINK, emoji_key, require_tier


def star_embed(message: discord.Message, count: int, emoji: str) -> discord.Embed:
    embed = discord.Embed(description=message.content or "*(sirf media)*", colour=PINK,
                          timestamp=message.created_at)
    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    embed.add_field(name="Asli message", value=f"[Yahan dekho]({message.jump_url}) in {message.channel.mention}")
    image = next((a for a in message.attachments if (a.content_type or "").startswith("image/")), None)
    if image:
        embed.set_image(url=image.url)
    embed.set_footer(text=f"{emoji} {count}")
    return embed


class Starboard(commands.Cog):
    starboard = app_commands.Group(
        name="starboard",
        description="Starboard settings",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._update(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._update(payload)

    async def _update(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        conf = self.bot.store.guild(payload.guild_id)["starboard"]
        if not conf["enabled"] or not conf["channel_id"] or payload.channel_id == conf["channel_id"]:
            return
        if emoji_key(payload.emoji) != emoji_key(conf["emoji"]):
            return
        guild = self.bot.get_guild(payload.guild_id)
        board = guild.get_channel(conf["channel_id"]) if guild else None
        source = guild.get_channel(payload.channel_id) if guild else None
        if not isinstance(board, discord.TextChannel) or source is None:
            return
        try:
            message = await source.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if message.author.bot:
            return
        reaction = next((r for r in message.reactions if emoji_key(r.emoji) == emoji_key(conf["emoji"])), None)
        count = reaction.count if reaction else 0
        posted_id = conf["posted"].get(str(message.id))
        try:
            if posted_id:
                star_msg = await board.fetch_message(posted_id)
                await star_msg.edit(embed=star_embed(message, count, conf["emoji"]))
            elif count >= conf["threshold"]:
                star_msg = await board.send(embed=star_embed(message, count, conf["emoji"]))
                conf["posted"][str(message.id)] = star_msg.id
                await self.bot.store.save()
        except discord.HTTPException:
            pass

    @starboard.command(name="setup", description="Pick the starboard channel, emoji and how many reactions it takes")
    @require_tier("admin")
    async def setup_board(self, interaction: discord.Interaction, channel: discord.TextChannel,
                          threshold: app_commands.Range[int, 1, 50] = 3, emoji: str = "⭐") -> None:
        conf = self.bot.store.guild(interaction.guild.id)["starboard"]
        conf.update({"channel_id": channel.id, "threshold": threshold, "emoji": emoji.strip(), "enabled": True})
        await self.bot.store.save()
        await interaction.response.send_message(
            f"{threshold} {emoji} milte hi message {channel.mention} mein frame ho jaayega.", ephemeral=True)

    @starboard.command(name="toggle", description="Turn the starboard on or off")
    @require_tier("admin")
    async def toggle(self, interaction: discord.Interaction, on: bool) -> None:
        self.bot.store.guild(interaction.guild.id)["starboard"]["enabled"] = on
        await self.bot.store.save()
        await interaction.response.send_message(f"Starboard {'ON' if on else 'OFF'}.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Starboard(bot))
