"""/panel: an admin control panel inside Discord. /help: what can I use?"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.welcome import build_welcome_embed
from bot.util import PINK, TIER_LABEL, member_level, require_tier

COMMANDS = {
    0: [("/help", "Yeh list"),
        ("/kamra naam | limit | lock", "Apne voice room ko sambhalo")],
    1: [("/warn", "Warning do (record mein save)"),
        ("/warnings", "Kisi ka record dekho"),
        ("/timeout", "Chup karao (helpers: max 1h)"),
        ("/untimeout", "Timeout hatao")],
    2: [("/kick", "Bahar nikaalo"),
        ("/purge", "Last N messages delete"),
        ("/slowmode", "Channel slow karo"),
        ("/lock  /unlock", "Channel band ya chalu"),
        ("/clearwarnings", "Warnings saaf"),
        ("/embed create | edit", "Embed banao ya badlo")],
    3: [("/ban  /unban", "Hamesha ke liye nikaalo / wapas lao"),
        ("/panel", "Yeh control panel"),
        ("/setup quickstart", "Roles ke naam se tiers auto-set"),
        ("/setup tier", "Kaunsa role helper/mod/admin"),
        ("/setup logchannel", "Mod log kahan jaaye"),
        ("/welcome channel | message | toggle | autorole | test", "Welcome settings"),
        ("/reactionroles create | add | remove | list | forget", "Reaction-role panels"),
        ("/autoreact add | remove | list | toggle", "Words Mausi ji reacts to"),
        ("/starboard setup | toggle", "Starboard"),
        ("/voicerooms setup | toggle", "Join-to-create voice rooms"),
        ("/setup channels", "Create starboard, drag, shayari, VC lobby channels"),
        ("/setup sortroles", "Put every role in the right order")],
}
LEVEL_NAME = {0: "sab log", 1: TIER_LABEL["helper"], 2: TIER_LABEL["mod"], 3: TIER_LABEL["admin"]}


def commands_embed(max_level: int) -> discord.Embed:
    embed = discord.Embed(title="Mausi ji ke commands", colour=PINK)
    for level in range(0, max_level + 1):
        lines = [f"`{name}` {desc}" for name, desc in COMMANDS[level]]
        embed.add_field(name=LEVEL_NAME[level], value="\n".join(lines), inline=False)
    return embed


def _mention_list(guild: discord.Guild, ids: list[int]) -> str:
    roles = [guild.get_role(i) for i in ids]
    return ", ".join(r.mention for r in roles if r) or "*koi nahi*"


def status_embed(guild: discord.Guild, conf: dict) -> discord.Embed:
    w = conf["welcome"]
    ch = guild.get_channel(w["channel_id"]) if w["channel_id"] else None
    log = guild.get_channel(conf["log_channel_id"]) if conf["log_channel_id"] else None
    on = lambda b: "🟢 on" if b else "⚫ off"  # noqa: E731
    me = guild.me
    missing = [name for name, ok in (
        ("Manage Roles", me.guild_permissions.manage_roles),
        ("Time out members", me.guild_permissions.moderate_members),
        ("Kick Members", me.guild_permissions.kick_members),
        ("Ban Members", me.guild_permissions.ban_members),
        ("Manage Messages", me.guild_permissions.manage_messages),
        ("Manage Channels", me.guild_permissions.manage_channels),
    ) if not ok]

    embed = discord.Embed(title=f"🎛️ {guild.name} control panel", colour=PINK)
    embed.add_field(name="Welcome", value=(
        f"Post: {on(w['enabled'])} in {ch.mention if ch else '*channel set nahi*'}\n"
        f"DM: {on(w['dm_enabled'])} • Goodbye: {on(w['goodbye_enabled'])}\n"
        f"Auto-roles: {_mention_list(guild, w['autorole_ids'])}"), inline=False)
    embed.add_field(name="Mod tiers", value=(
        f"Helpers: {_mention_list(guild, conf['tiers']['helper'])}\n"
        f"Mods: {_mention_list(guild, conf['tiers']['mod'])}\n"
        f"Admins: {_mention_list(guild, conf['tiers']['admin'])} (+ anyone with Administrator)"), inline=False)
    embed.add_field(name="Mod log", value=log.mention if log else "*set nahi* (`/setup logchannel`)", inline=True)
    embed.add_field(name="Reaction-role panels", value=str(len(conf["reaction_roles"])), inline=True)
    embed.add_field(name="Warnings on record", value=str(sum(len(v) for v in conf["warnings"].values())), inline=True)
    embed.add_field(name="Mera role ki position", value=f"{me.top_role.mention} (jo roles main dun, woh isse neeche hone chahiye)",
                    inline=False)
    if missing:
        embed.add_field(name="⚠️ Mujhe yeh permissions chahiye", value=", ".join(missing), inline=False)
    return embed


class PanelView(discord.ui.View):
    def __init__(self, bot, owner_id: int) -> None:
        super().__init__(timeout=600)
        self.bot, self.owner_id = bot, owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Yeh panel tera nahi hai. Khud `/panel` chala.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        await interaction.response.edit_message(embed=status_embed(interaction.guild, conf), view=self)

    @discord.ui.button(label="Welcome on/off", emoji="👋", style=discord.ButtonStyle.primary)
    async def toggle_welcome(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        conf["welcome"]["enabled"] = not conf["welcome"]["enabled"]
        await self.bot.store.save()
        await self._refresh(interaction)

    @discord.ui.button(label="DM on/off", emoji="💌", style=discord.ButtonStyle.secondary)
    async def toggle_dm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        conf["welcome"]["dm_enabled"] = not conf["welcome"]["dm_enabled"]
        await self.bot.store.save()
        await self._refresh(interaction)

    @discord.ui.button(label="Test welcome", emoji="🧪", style=discord.ButtonStyle.secondary)
    async def test_welcome(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        await interaction.response.send_message(embed=build_welcome_embed(interaction.user, conf), ephemeral=True)

    @discord.ui.button(label="Commands", emoji="📜", style=discord.ButtonStyle.secondary)
    async def show_commands(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=commands_embed(3), ephemeral=True)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.success)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._refresh(interaction)


class Panel(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(name="panel", description="Open the bot's control panel (admins)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @require_tier("admin")
    async def panel(self, interaction: discord.Interaction) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        await interaction.response.send_message(embed=status_embed(interaction.guild, conf),
                                                view=PanelView(self.bot, interaction.user.id), ephemeral=True)

    @app_commands.command(name="help", description="Commands you're allowed to use")
    @app_commands.guild_only()
    async def help(self, interaction: discord.Interaction) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        await interaction.response.send_message(embed=commands_embed(member_level(interaction.user, conf)),
                                                ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Panel(bot))
