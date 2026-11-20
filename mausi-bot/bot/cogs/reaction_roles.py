"""Reaction roles: react to a message, get a role. Unreact, lose it."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.actions import load_presets, post_preset
from bot.util import PINK, emoji_key, require_tier


class ReactionRoles(commands.Cog):
    rr = app_commands.Group(
        name="reactionroles",
        description="Reaction-role panels",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    def __init__(self, bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------ helpers
    def _panel(self, guild_id: int, message_id: int):
        return self.bot.store.guild(guild_id)["reaction_roles"].get(str(message_id))

    async def _member(self, guild: discord.Guild, user_id: int):
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return None
        return member

    # ------------------------------------------------------------ events
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        panel = self._panel(payload.guild_id, payload.message_id)
        if not panel:
            return
        role_id = panel["mapping"].get(emoji_key(payload.emoji))
        guild = self.bot.get_guild(payload.guild_id)
        if not role_id or guild is None:
            return
        member = payload.member or await self._member(guild, payload.user_id)
        role = guild.get_role(role_id)
        if member is None or member.bot or role is None:
            return
        try:
            if panel.get("exclusive"):
                others = [guild.get_role(r) for r in panel["mapping"].values() if r != role_id]
                others = [r for r in others if r and r in member.roles]
                if others:
                    await member.remove_roles(*others, reason="Reaction role (only one allowed)")
                    channel = guild.get_channel(panel["channel_id"])
                    if isinstance(channel, discord.TextChannel):
                        try:
                            msg = await channel.fetch_message(payload.message_id)
                            for reaction in msg.reactions:
                                key = emoji_key(reaction.emoji)
                                if key != emoji_key(payload.emoji) and key in panel["mapping"]:
                                    await msg.remove_reaction(reaction.emoji, member)
                        except discord.HTTPException:
                            pass
            await member.add_roles(role, reason="Reaction role")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        panel = self._panel(payload.guild_id, payload.message_id)
        if not panel:
            return
        role_id = panel["mapping"].get(emoji_key(payload.emoji))
        guild = self.bot.get_guild(payload.guild_id)
        if not role_id or guild is None:
            return
        member = await self._member(guild, payload.user_id)
        role = guild.get_role(role_id)
        if member is None or role is None or role not in member.roles:
            return
        try:
            await member.remove_roles(role, reason="Reaction role removed")
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ commands
    async def preset_autocomplete(self, interaction: discord.Interaction, current: str):
        presets = load_presets()
        return [
            app_commands.Choice(name=f"{key}: {p['title']}"[:100], value=key)
            for key, p in presets.items() if current.lower() in key.lower()
        ][:25]

    @rr.command(name="create", description="Post a ready-made reaction-role panel (pronouns, vibes, identity...)")
    @app_commands.describe(
        preset="Which panel to post (from presets.json)",
        channel="Where to post it",
        create_missing="Create any roles in the preset that don't exist yet (no permissions, just a name)",
    )
    @app_commands.autocomplete(preset=preset_autocomplete)
    @require_tier("admin")
    async def create(self, interaction: discord.Interaction, preset: str, channel: discord.TextChannel,
                     create_missing: bool = False) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        url, problems = await post_preset(self.bot, interaction.guild, preset, channel, create_missing)
        if url is None:
            await interaction.followup.send("Panel nahi bana:\n" + "\n".join(problems), ephemeral=True)
            return
        text = f"Panel ready: {url}"
        if problems:
            text += "\n\nDhyaan de:\n" + "\n".join(problems)
        await interaction.followup.send(text, ephemeral=True)

    @rr.command(name="add", description="Add an emoji -> role pair to a panel I posted")
    @app_commands.describe(message_id="Right-click the panel > Copy Message ID (turn on Developer Mode first)")
    @require_tier("admin")
    async def add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        panel = conf["reaction_roles"].get(message_id.strip())
        if not panel:
            await interaction.response.send_message("Yeh message mera panel nahi hai.", ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("Yeh role mere role se upar hai.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(panel["channel_id"])
        try:
            msg = await channel.fetch_message(int(message_id))
            await msg.add_reaction(emoji.strip())
        except (discord.HTTPException, AttributeError, ValueError):
            await interaction.response.send_message("Panel ya emoji mein gadbad hai. Check kar le.", ephemeral=True)
            return
        panel["mapping"][emoji_key(emoji)] = role.id
        embed = msg.embeds[0] if msg.embeds else discord.Embed(title=panel["title"], colour=PINK)
        embed.description = (embed.description or "") + f"\n{emoji.strip()}  {role.mention}"
        await msg.edit(embed=embed)
        await self.bot.store.save()
        await interaction.response.send_message("Jod diya.", ephemeral=True)

    @rr.command(name="remove", description="Remove an emoji from a panel")
    @require_tier("admin")
    async def remove(self, interaction: discord.Interaction, message_id: str, emoji: str) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        panel = conf["reaction_roles"].get(message_id.strip())
        if not panel or emoji_key(emoji) not in panel["mapping"]:
            await interaction.response.send_message("Us panel pe yeh emoji hai hi nahi.", ephemeral=True)
            return
        del panel["mapping"][emoji_key(emoji)]
        await self.bot.store.save()
        await interaction.response.send_message(
            "Hata diya. Panel ka text khud edit karna ho toh naya panel bana lo.", ephemeral=True)

    @rr.command(name="list", description="Show every reaction-role panel")
    @require_tier("admin")
    async def list_panels(self, interaction: discord.Interaction) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        panels = conf["reaction_roles"]
        if not panels:
            await interaction.response.send_message("Abhi koi panel nahi hai. `/reactionroles create` chala.", ephemeral=True)
            return
        lines = []
        for mid, p in panels.items():
            channel = interaction.guild.get_channel(p["channel_id"])
            where = channel.mention if channel else "(channel gone)"
            lines.append(f"**{p['title']}** in {where} • `{mid}` • {len(p['mapping'])} roles"
                         + (" • only one" if p.get("exclusive") else ""))
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @rr.command(name="forget", description="Stop a panel from giving roles (the message stays)")
    @require_tier("admin")
    async def forget(self, interaction: discord.Interaction, message_id: str) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        if conf["reaction_roles"].pop(message_id.strip(), None) is None:
            await interaction.response.send_message("Aisa koi panel nahi.", ephemeral=True)
            return
        await self.bot.store.save()
        await interaction.response.send_message("Bhool gayi. Message ab chaho toh delete kar do.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(ReactionRoles(bot))
