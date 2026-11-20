"""Moderation commands, gated by the bot's own role tiers.

Each command's tier is set per server (dashboard > Command access); the
defaults live in bot/util.py COMMAND_ACCESS_DEFAULTS. Discord also hides each
command from members who lack the matching Discord permission.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.util import (PINK, hierarchy_problem, human_duration, member_level, parse_duration,
                      require_access, send_log)

HELPER_MAX_TIMEOUT = timedelta(hours=1)
DISCORD_MAX_TIMEOUT = timedelta(days=28)


def action_embed(action: str, target: discord.abc.User, mod: discord.abc.User,
                 reason: Optional[str], extra: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(title=action, colour=PINK, timestamp=discord.utils.utcnow())
    embed.add_field(name="Kiske saath", value=f"{target.mention} (`{target.id}`)", inline=False)
    embed.add_field(name="Kisne kiya", value=mod.mention, inline=True)
    embed.add_field(name="Kyun", value=reason or "koi reason nahi diya", inline=True)
    if extra:
        embed.add_field(name="Details", value=extra, inline=False)
    return embed


async def try_dm(user: discord.abc.User, text: str) -> None:
    try:
        await user.send(text)
    except discord.HTTPException:
        pass


class Moderation(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    async def _guard(self, interaction: discord.Interaction, target: discord.Member) -> bool:
        problem = hierarchy_problem(interaction.user, target)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return False
        return True

    # ------------------------------------------------------------ warnings
    @app_commands.command(name="warn", description="Warn a member (saved to their record)")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @require_access("warn")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        if not await self._guard(interaction, member):
            return
        conf = self.bot.store.guild(interaction.guild.id)
        record = conf["warnings"].setdefault(str(member.id), [])
        record.append({"reason": reason, "mod_id": interaction.user.id,
                       "ts": int(discord.utils.utcnow().timestamp())})
        await self.bot.store.save()
        await try_dm(member, f"**{interaction.guild.name}** mein tujhe warning mili hai: {reason}")
        await interaction.response.send_message(
            f"{member.mention} ko warning de di. Total warnings: **{len(record)}**.",
            allowed_mentions=discord.AllowedMentions.none())
        await send_log(self.bot, interaction.guild, action_embed("⚠️ Warning", member, interaction.user, reason,
                                                                 f"Total warnings: {len(record)}"))

    @app_commands.command(name="warnings", description="See a member's warnings")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @require_access("warnings")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        record = conf["warnings"].get(str(member.id), [])
        if not record:
            await interaction.response.send_message(f"{member.display_name} ka record saaf hai. Shareef bachcha.",
                                                    ephemeral=True)
            return
        lines = [f"{i}. <t:{w['ts']}:d> by <@{w['mod_id']}>: {w['reason']}" for i, w in enumerate(record[-15:], 1)]
        embed = discord.Embed(title=f"{member.display_name} ki warnings ({len(record)})",
                              description="\n".join(lines), colour=PINK)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="Wipe a member's warnings")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @require_access("clearwarnings")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        count = len(conf["warnings"].pop(str(member.id), []))
        await self.bot.store.save()
        await interaction.response.send_message(f"{member.display_name} ki {count} warnings saaf.", ephemeral=True)
        await send_log(self.bot, interaction.guild, action_embed("🧽 Warnings cleared", member, interaction.user,
                                                                 None, f"{count} removed"))

    # ------------------------------------------------------------ timeouts
    @app_commands.command(name="timeout", description="Time someone out, e.g. 10m, 2h, 1d")
    @app_commands.describe(duration="Like 10m, 1h30m, 2d. Helpers can go up to 1h.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @require_access("timeout")
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str,
                      reason: Optional[str] = None) -> None:
        if not await self._guard(interaction, member):
            return
        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message("Duration samajh nahi aaya. Aise likh: `10m`, `2h`, `1d`.",
                                                    ephemeral=True)
            return
        conf = self.bot.store.guild(interaction.guild.id)
        if member_level(interaction.user, conf) < 2 and delta > HELPER_MAX_TIMEOUT:
            await interaction.response.send_message("Munshi ji, tum max 1 ghanta de sakte ho. Zyada ke liye aunty ko bulao.",
                                                    ephemeral=True)
            return
        delta = min(delta, DISCORD_MAX_TIMEOUT)
        try:
            await member.timeout(delta, reason=f"{interaction.user}: {reason or 'no reason'}")
        except discord.HTTPException:
            await interaction.response.send_message("Nahi ho paaya. Mujhe 'Time out members' permission chahiye.",
                                                    ephemeral=True)
            return
        await interaction.response.send_message(
            f"🤐 {member.mention} ko {human_duration(delta)} ke liye chup kara diya.",
            allowed_mentions=discord.AllowedMentions.none())
        await send_log(self.bot, interaction.guild, action_embed("🤐 Timeout", member, interaction.user, reason,
                                                                 human_duration(delta)))

    @app_commands.command(name="untimeout", description="Lift someone's timeout")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @require_access("untimeout")
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member) -> None:
        try:
            await member.timeout(None, reason=f"Lifted by {interaction.user}")
        except discord.HTTPException:
            await interaction.response.send_message("Nahi ho paaya.", ephemeral=True)
            return
        await interaction.response.send_message(f"{member.display_name} ab bol sakti hai.", ephemeral=True)
        await send_log(self.bot, interaction.guild, action_embed("🗣️ Timeout lifted", member, interaction.user, None))

    # ------------------------------------------------------------ kick / ban
    @app_commands.command(name="kick", description="Kick a member out of the server")
    @app_commands.guild_only()
    @app_commands.default_permissions(kick_members=True)
    @require_access("kick")
    async def kick(self, interaction: discord.Interaction, member: discord.Member,
                   reason: Optional[str] = None) -> None:
        if not await self._guard(interaction, member):
            return
        await try_dm(member, f"Tujhe **{interaction.guild.name}** se kick kiya gaya. Reason: {reason or 'nahi diya'}")
        try:
            await member.kick(reason=f"{interaction.user}: {reason or 'no reason'}")
        except discord.HTTPException:
            await interaction.response.send_message("Kick nahi ho paaya. Mujhe 'Kick Members' chahiye.", ephemeral=True)
            return
        await interaction.response.send_message(f"👢 {member.display_name} ko bahar ka raasta dikha diya.")
        await send_log(self.bot, interaction.guild, action_embed("👢 Kick", member, interaction.user, reason))

    @app_commands.command(name="ban", description="Ban someone (works even if they already left)")
    @app_commands.describe(delete_messages="Delete their messages from the last N days (0-7)")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @require_access("ban")
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: Optional[str] = None,
                  delete_messages: app_commands.Range[int, 0, 7] = 0) -> None:
        member = interaction.guild.get_member(user.id)
        if member and not await self._guard(interaction, member):
            return
        if member:
            await try_dm(member, f"Tujhe **{interaction.guild.name}** se ban kiya gaya. Reason: {reason or 'nahi diya'}")
        try:
            await interaction.guild.ban(user, reason=f"{interaction.user}: {reason or 'no reason'}",
                                        delete_message_seconds=delete_messages * 86400)
        except discord.HTTPException:
            await interaction.response.send_message("Ban nahi ho paaya. Mujhe 'Ban Members' chahiye.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔨 {user.name} hamesha ke liye nikaal di gayi.")
        await send_log(self.bot, interaction.guild, action_embed("🔨 Ban", user, interaction.user, reason))

    @app_commands.command(name="unban", description="Unban someone using their user ID")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @require_access("unban")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: Optional[str] = None) -> None:
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason or 'no reason'}")
        except (ValueError, discord.HTTPException):
            await interaction.response.send_message("Yeh ID ban list mein nahi mili.", ephemeral=True)
            return
        await interaction.response.send_message(f"{user.name} ka ban hata diya.", ephemeral=True)
        await send_log(self.bot, interaction.guild, action_embed("🕊️ Unban", user, interaction.user, reason))

    # ------------------------------------------------------------ channel tools
    @app_commands.command(name="purge", description="Delete the last N messages here (max 100)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @require_access("purge")
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100],
                    only_from: Optional[discord.Member] = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        check = (lambda m: m.author.id == only_from.id) if only_from else (lambda m: True)
        try:
            deleted = await interaction.channel.purge(limit=amount, check=check)
        except discord.HTTPException:
            await interaction.followup.send("Nahi ho paaya. Mujhe 'Manage Messages' chahiye.", ephemeral=True)
            return
        await interaction.followup.send(f"🧹 {len(deleted)} messages saaf.", ephemeral=True)
        await send_log(self.bot, interaction.guild, action_embed(
            "🧹 Purge", interaction.user, interaction.user, None,
            f"{len(deleted)} messages in {interaction.channel.mention}"))

    @app_commands.command(name="slowmode", description="Set slowmode in this channel (0 to turn off)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @require_access("slowmode")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]) -> None:
        try:
            await interaction.channel.edit(slowmode_delay=seconds)
        except discord.HTTPException:
            await interaction.response.send_message("Nahi ho paaya. Mujhe 'Manage Channels' chahiye.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Slowmode band." if seconds == 0 else f"🐢 Slowmode: {seconds}s. Aaram se, behen.")

    async def _set_lock(self, interaction: discord.Interaction, locked: bool) -> None:
        channel = interaction.channel
        everyone = interaction.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False if locked else None
        try:
            await channel.set_permissions(everyone, overwrite=overwrite,
                                          reason=f"{'Lock' if locked else 'Unlock'} by {interaction.user}")
        except discord.HTTPException:
            await interaction.response.send_message("Nahi ho paaya. Mujhe 'Manage Roles' chahiye.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🔒 Channel band. Sab chup, aunty aa gayi." if locked else "🔓 Channel khul gaya. Chugli resume karo.")
        await send_log(self.bot, interaction.guild, action_embed(
            "🔒 Lock" if locked else "🔓 Unlock", interaction.user, interaction.user, None, channel.mention))

    @app_commands.command(name="lock", description="Stop @everyone from typing in this channel")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @require_access("lock")
    async def lock(self, interaction: discord.Interaction) -> None:
        await self._set_lock(interaction, True)

    @app_commands.command(name="unlock", description="Let @everyone type in this channel again")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @require_access("lock")
    async def unlock(self, interaction: discord.Interaction) -> None:
        await self._set_lock(interaction, False)


async def setup(bot) -> None:
    await bot.add_cog(Moderation(bot))
