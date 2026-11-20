"""/embed: make and edit fancy embed messages (locked to the 'embed' tier, mods by default)."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.actions import EmbedError, build_embed, embed_to_data, parse_message_link
from bot.util import require_access, send_log, PINK


class EmbedModal(discord.ui.Modal):
    def __init__(self, cog: "Embeds", channel: discord.TextChannel, existing: Optional[discord.Message] = None) -> None:
        super().__init__(title="Embed banao" if existing is None else "Embed badlo", timeout=900)
        self.cog, self.channel, self.existing = cog, channel, existing
        d = embed_to_data(existing.embeds[0]) if existing and existing.embeds else {}
        self.t = discord.ui.TextInput(label="Title", required=False, max_length=256, default=d.get("title", ""))
        self.desc = discord.ui.TextInput(label="Text (markdown works)", style=discord.TextStyle.paragraph,
                                         required=False, max_length=4000, default=d.get("description", ""))
        self.colour = discord.ui.TextInput(label="Colour, like #ff3d8b", required=False, max_length=7,
                                           default=d.get("color", "#ff3d8b"))
        self.image = discord.ui.TextInput(label="Image link (optional)", required=False, max_length=500,
                                          default=d.get("image", ""))
        self.footer = discord.ui.TextInput(label="Footer (optional)", required=False, max_length=300,
                                           default=d.get("footer", ""))
        for item in (self.t, self.desc, self.colour, self.image, self.footer):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        data = {"title": str(self.t), "description": str(self.desc), "color": str(self.colour),
                "image": str(self.image), "footer": str(self.footer)}
        if self.existing and self.existing.embeds:  # keep fields/author/etc. the modal can't show
            old = embed_to_data(self.existing.embeds[0])
            data = {**old, **data}
        try:
            embed = build_embed(data)
        except EmbedError as exc:
            await interaction.response.send_message(f"Gadbad: {exc}", ephemeral=True)
            return
        if self.existing:
            await self.existing.edit(embed=embed)
            await interaction.response.send_message("Embed badal diya. ✨", ephemeral=True)
            return
        await interaction.response.send_message("Aisa dikhega. Post kar doon?", embed=embed,
                                                view=PostView(self.cog, self.channel, embed, interaction.user.id),
                                                ephemeral=True)


class PostView(discord.ui.View):
    def __init__(self, cog: "Embeds", channel: discord.TextChannel, embed: discord.Embed, owner_id: int) -> None:
        super().__init__(timeout=600)
        self.cog, self.channel, self.embed, self.owner_id = cog, channel, embed, owner_id

    @discord.ui.button(label="Post karo", emoji="📤", style=discord.ButtonStyle.success)
    async def post(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            msg = await self.channel.send(embed=self.embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await interaction.response.edit_message(content=f"{self.channel.mention} mein post nahi kar paayi. Permissions check karo.",
                                                    view=None)
            return
        await interaction.response.edit_message(content=f"Post ho gaya: {msg.jump_url}", view=None)
        log = discord.Embed(title="📝 Embed posted", colour=PINK, description=f"{interaction.user.mention} in {self.channel.mention}\n{msg.jump_url}")
        await send_log(self.cog.bot, interaction.guild, log)

    @discord.ui.button(label="Rehne do", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Theek hai, kuch post nahi kiya.", embed=None, view=None)


class Embeds(commands.Cog):
    embed = app_commands.Group(name="embed", description="Make and edit embed messages", guild_only=True,
                               default_permissions=discord.Permissions(manage_messages=True))

    def __init__(self, bot) -> None:
        self.bot = bot

    @embed.command(name="create", description="Make an embed and post it (you get a preview first)")
    @app_commands.describe(channel="Where to post it (default: this channel)")
    @require_access("embed")
    async def create(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        await interaction.response.send_modal(EmbedModal(self, channel or interaction.channel))

    @embed.command(name="edit", description="Edit an embed Mausi ji posted (paste the message link)")
    @require_access("embed")
    async def edit(self, interaction: discord.Interaction, message_link: str) -> None:
        ids = parse_message_link(message_link)
        channel = interaction.guild.get_channel(ids[0]) if ids else None
        try:
            msg = await channel.fetch_message(ids[1]) if channel else None
        except discord.HTTPException:
            msg = None
        if msg is None or msg.author.id != self.bot.user.id or not msg.embeds:
            await interaction.response.send_message("Yeh mera embed wala message nahi hai. Message pe right-click > Copy Message Link.",
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(EmbedModal(self, channel, existing=msg))


async def setup(bot) -> None:
    await bot.add_cog(Embeds(bot))
