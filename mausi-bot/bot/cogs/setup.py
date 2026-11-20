"""Server setup: which roles are helpers/mods/admins, and the mod-log channel."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.actions import ensure_channels, sort_roles
from bot.util import TIER_LABEL, require_tier

TIER_CHOICES = [app_commands.Choice(name=TIER_LABEL[t], value=t) for t in ("helper", "mod", "admin")]


class Setup(commands.Cog):
    setup_group = app_commands.Group(
        name="setup",
        description="Set up mod tiers and the log channel",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot) -> None:
        self.bot = bot

    @setup_group.command(name="tier", description="Give a role helper, mod or admin powers in the bot")
    @app_commands.choices(tier=TIER_CHOICES, action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
    ])
    @require_tier("admin")
    async def tier(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                   tier: app_commands.Choice[str], role: discord.Role) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        ids = conf["tiers"][tier.value]
        if action.value == "add":
            if role.id not in ids:
                ids.append(role.id)
            msg = f"{role.mention} ab **{tier.name}** hai."
        else:
            if role.id in ids:
                ids.remove(role.id)
            msg = f"{role.mention} ab **{tier.name}** nahi hai."
        await self.bot.store.save()
        await interaction.response.send_message(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @setup_group.command(name="logchannel", description="Where moderation actions get logged")
    @require_tier("admin")
    async def logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        conf["log_channel_id"] = channel.id
        await self.bot.store.save()
        await interaction.response.send_message(f"Mod log ab {channel.mention} mein.", ephemeral=True)

    @setup_group.command(name="quickstart",
                         description="Auto-fill tiers from your server's role names (aunty, munshi, ranivati)")
    @require_tier("admin")
    async def quickstart(self, interaction: discord.Interaction) -> None:
        """Matches the roles already set up in mera mirchidaar bhosada."""
        guild = interaction.guild
        conf = self.bot.store.guild(guild.id)
        wanted = {
            "helper": ["rishwatkhor munshi"],
            "mod": ["lathi-charge wali aunty"],
            "admin": ["ranivati hijdavati"],
        }
        found = []
        for tier, names in wanted.items():
            for name in names:
                role = discord.utils.get(guild.roles, name=name)
                if role and role.id not in conf["tiers"][tier]:
                    conf["tiers"][tier].append(role.id)
                    found.append(f"{role.name} → {TIER_LABEL[tier]}")
        newbie = discord.utils.get(guild.roles, name="abhi tak shareef")
        if newbie and newbie < guild.me.top_role and newbie.id not in conf["welcome"]["autorole_ids"]:
            conf["welcome"]["autorole_ids"].append(newbie.id)
            found.append(f"{newbie.name} → auto-role for new members")
        intro = discord.utils.get(guild.text_channels, name="aao-baitho-intro-do") or \
            discord.utils.get(guild.text_channels, name="naye-bhakt")
        if intro and not conf["welcome"]["channel_id"]:
            conf["welcome"]["channel_id"] = intro.id
            found.append(f"welcome messages → #{intro.name}")
        log = discord.utils.get(guild.text_channels, name="aunty-ki-kitty-party")
        if log and not conf["log_channel_id"]:
            conf["log_channel_id"] = log.id
            found.append(f"mod log → #{log.name}")
        stars = discord.utils.get(guild.text_channels, name="tareef-ki-deewar")
        if stars and not conf["starboard"]["channel_id"]:
            conf["starboard"]["channel_id"] = stars.id
            found.append(f"starboard → #{stars.name}")
        lobby = discord.utils.get(guild.voice_channels, name="➕ naya kamra banao")
        if lobby and not conf["voicerooms"]["lobby_channel_id"]:
            conf["voicerooms"]["lobby_channel_id"] = lobby.id
            found.append(f"voice rooms lobby → {lobby.name}")
        await self.bot.store.save()
        await interaction.response.send_message(
            ("Ho gaya:\n" + "\n".join(f"• {f}" for f in found)) if found else
            "Kuch naya match nahi hua. Roles ke naam check kar ya `/setup tier` se khud set kar.",
            ephemeral=True)


    @setup_group.command(name="channels",
                         description="Create the starboard, bot-commands, drag, shayari and join-to-create channels")
    @require_tier("admin")
    async def channels(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            made = await ensure_channels(self.bot, interaction.guild)
        except discord.HTTPException:
            await interaction.followup.send("Channel nahi ban paaye. Mujhe 'Manage Channels' chahiye.", ephemeral=True)
            return
        await interaction.followup.send(("Bana diye: " + ", ".join(made)) if made else "Sab channels pehle se hain.",
                                        ephemeral=True)

    @setup_group.command(name="sortroles",
                         description="Put every role below me in the right order (colours above vibes, etc.)")
    @require_tier("admin")
    async def sortroles(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        conf = self.bot.store.guild(interaction.guild.id)
        try:
            count, missing = await sort_roles(interaction.guild, conf["role_order"])
        except discord.HTTPException as e:
            await interaction.followup.send(f"Nahi ho paaya ({e.status}). Mujhe 'Manage Roles' chahiye.", ephemeral=True)
            return
        text = f"{count} roles line mein laga diye."
        if missing:
            text += "\nYeh naam nahi mile (spelling check karo): " + ", ".join(missing[:10])
        await interaction.followup.send(text, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Setup(bot))
