"""Join-to-create voice rooms: join the lobby, get your own room, it vanishes when empty."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.util import require_tier


class VoiceRooms(commands.Cog):
    rooms = app_commands.Group(name="voicerooms", description="Join-to-create voice rooms",
                               guild_only=True, default_permissions=discord.Permissions(manage_guild=True))
    room = app_commands.Group(name="kamra", description="Manage your own voice room", guild_only=True)

    def __init__(self, bot) -> None:
        self.bot = bot

    def _conf(self, guild_id: int) -> dict:
        return self.bot.store.guild(guild_id)["voicerooms"]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState) -> None:
        conf = self._conf(member.guild.id)
        # Left a temp room: delete it once empty.
        if before.channel and str(before.channel.id) in conf["rooms"] and before.channel != after.channel:
            if not before.channel.members:
                try:
                    await before.channel.delete(reason="Temp room empty")
                except discord.HTTPException:
                    pass
                conf["rooms"].pop(str(before.channel.id), None)
                await self.bot.store.save()
        # Joined the lobby: make a room and move them in.
        if conf["enabled"] and after.channel and after.channel.id == conf["lobby_channel_id"] and not member.bot:
            category = member.guild.get_channel(conf["category_id"]) if conf["category_id"] else after.channel.category
            name = conf["name_template"].replace("{name}", member.display_name)[:95]
            try:
                channel = await member.guild.create_voice_channel(
                    name, category=category if isinstance(category, discord.CategoryChannel) else None,
                    overwrites={**(category.overwrites if isinstance(category, discord.CategoryChannel) else {}),
                                member: discord.PermissionOverwrite(manage_channels=True, move_members=True,
                                                                    connect=True, speak=True)},
                    reason=f"Join-to-create for {member}")
                conf["rooms"][str(channel.id)] = member.id
                await self.bot.store.save()
                await member.move_to(channel)
            except discord.HTTPException:
                pass

    async def _owned_room(self, interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
        voice = interaction.user.voice
        conf = self._conf(interaction.guild.id)
        if not voice or not voice.channel or conf["rooms"].get(str(voice.channel.id)) != interaction.user.id:
            await interaction.response.send_message("Pehle apne kamre mein baith, phir hukum chala.", ephemeral=True)
            return None
        return voice.channel

    @rooms.command(name="setup", description="Choose the lobby channel people join to get a room")
    @require_tier("admin")
    async def setup_rooms(self, interaction: discord.Interaction, lobby: discord.VoiceChannel,
                          category: Optional[discord.CategoryChannel] = None) -> None:
        conf = self._conf(interaction.guild.id)
        conf.update({"lobby_channel_id": lobby.id, "category_id": category.id if category else None, "enabled": True})
        await self.bot.store.save()
        await interaction.response.send_message(f"{lobby.mention} join karte hi naya kamra banega.", ephemeral=True)

    @rooms.command(name="toggle", description="Turn join-to-create on or off")
    @require_tier("admin")
    async def toggle(self, interaction: discord.Interaction, on: bool) -> None:
        self._conf(interaction.guild.id)["enabled"] = on
        await self.bot.store.save()
        await interaction.response.send_message(f"Voice rooms {'ON' if on else 'OFF'}.", ephemeral=True)

    @room.command(name="naam", description="Rename your voice room")
    async def rename(self, interaction: discord.Interaction, name: str) -> None:
        channel = await self._owned_room(interaction)
        if channel:
            await channel.edit(name=name[:95])
            await interaction.response.send_message("Naya naam laga diya.", ephemeral=True)

    @room.command(name="limit", description="Max people in your room (0 = no limit)")
    async def limit(self, interaction: discord.Interaction, people: app_commands.Range[int, 0, 99]) -> None:
        channel = await self._owned_room(interaction)
        if channel:
            await channel.edit(user_limit=people)
            await interaction.response.send_message(f"Limit: {people or 'koi nahi'}.", ephemeral=True)

    @room.command(name="lock", description="Lock or unlock your room")
    async def lock(self, interaction: discord.Interaction, locked: bool) -> None:
        channel = await self._owned_room(interaction)
        if channel:
            ow = channel.overwrites_for(interaction.guild.default_role)
            ow.connect = False if locked else None
            await channel.set_permissions(interaction.guild.default_role, overwrite=ow)
            await interaction.response.send_message("🔒 Band." if locked else "🔓 Khula.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(VoiceRooms(bot))
