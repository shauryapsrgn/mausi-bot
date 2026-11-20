"""Welcome (and optional goodbye) messages, DMs and auto-roles."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.util import PINK, render, require_tier


def build_welcome_embed(member: discord.Member, conf: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Naya shikaar aaya: {member.display_name}",
        description=render(conf["welcome"]["message"], member),
        colour=PINK,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"{member.guild.name} • member #{member.guild.member_count}")
    return embed


class MessageModal(discord.ui.Modal):
    def __init__(self, cog: "Welcome", field: str, current: str) -> None:
        title = "Welcome message" if field == "message" else ("DM message" if field == "dm_message" else "Goodbye message")
        super().__init__(title=title)
        self.cog, self.field = cog, field
        self.text = discord.ui.TextInput(
            label="Text ({user} {name} {server} {count} {#channel})",
            style=discord.TextStyle.paragraph,
            default=current[:1500],
            max_length=1500,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        conf = self.cog.bot.store.guild(interaction.guild.id)
        conf["welcome"][self.field] = str(self.text.value)
        await self.cog.bot.store.save()
        await interaction.response.send_message("Saved. `/welcome test` se dekh le kaisa lagta hai.", ephemeral=True)


class Welcome(commands.Cog):
    welcome = app_commands.Group(
        name="welcome",
        description="Welcome messages, DMs and auto-roles",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------ events
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        conf = self.bot.store.guild(member.guild.id)
        w = conf["welcome"]

        roles = [member.guild.get_role(rid) for rid in w["autorole_ids"]]
        roles = [r for r in roles if r and r < member.guild.me.top_role]
        if roles:
            try:
                await member.add_roles(*roles, reason="Auto-role on join")
            except discord.HTTPException:
                pass

        if w["enabled"] and w["channel_id"]:
            channel = member.guild.get_channel(w["channel_id"])
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(content=member.mention, embed=build_welcome_embed(member, conf))
                except discord.HTTPException:
                    pass

        if w["dm_enabled"]:
            try:
                await member.send(render(w["dm_message"], member))
            except discord.HTTPException:
                pass  # DMs closed, nothing to do

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        conf = self.bot.store.guild(member.guild.id)
        w = conf["welcome"]
        if not (w["goodbye_enabled"] and w["channel_id"]):
            return
        channel = member.guild.get_channel(w["channel_id"])
        if isinstance(channel, discord.TextChannel):
            text = w["goodbye_message"].replace("{name}", member.display_name).replace("{server}", member.guild.name)
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------ commands
    @welcome.command(name="channel", description="Choose the channel welcome messages go to")
    @require_tier("admin")
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        conf["welcome"]["channel_id"] = channel.id
        await self.bot.store.save()
        await interaction.response.send_message(f"Welcome messages ab {channel.mention} mein aayenge.", ephemeral=True)

    @welcome.command(name="message", description="Edit the welcome, DM or goodbye text")
    @app_commands.choices(which=[
        app_commands.Choice(name="welcome post", value="message"),
        app_commands.Choice(name="welcome DM", value="dm_message"),
        app_commands.Choice(name="goodbye post", value="goodbye_message"),
    ])
    @require_tier("admin")
    async def set_message(self, interaction: discord.Interaction, which: app_commands.Choice[str]) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        await interaction.response.send_modal(MessageModal(self, which.value, conf["welcome"][which.value]))

    @welcome.command(name="toggle", description="Turn welcome posts, welcome DMs or goodbye posts on/off")
    @app_commands.choices(what=[
        app_commands.Choice(name="welcome post", value="enabled"),
        app_commands.Choice(name="welcome DM", value="dm_enabled"),
        app_commands.Choice(name="goodbye post", value="goodbye_enabled"),
    ])
    @require_tier("admin")
    async def toggle(self, interaction: discord.Interaction, what: app_commands.Choice[str], on: bool) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        conf["welcome"][what.value] = on
        await self.bot.store.save()
        await interaction.response.send_message(f"{what.name}: {'ON' if on else 'OFF'}", ephemeral=True)

    @welcome.command(name="autorole", description="Add or remove a role everyone gets on joining")
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
    ])
    @require_tier("admin")
    async def autorole(self, interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        ids = conf["welcome"]["autorole_ids"]
        if action.value == "add":
            if role >= interaction.guild.me.top_role:
                await interaction.response.send_message(
                    "Yeh role mere role se upar hai, main ise de nahi paaungi. Mera role upar khiskao.", ephemeral=True)
                return
            if role.id not in ids:
                ids.append(role.id)
            msg = f"Naye log ko ab {role.mention} milega."
        else:
            if role.id in ids:
                ids.remove(role.id)
            msg = f"{role.mention} ab auto-role nahi hai."
        await self.bot.store.save()
        await interaction.response.send_message(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @welcome.command(name="test", description="Preview the welcome message using yourself")
    @require_tier("admin")
    async def test(self, interaction: discord.Interaction) -> None:
        conf = self.bot.store.guild(interaction.guild.id)
        await interaction.response.send_message(
            embed=build_welcome_embed(interaction.user, conf), ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Welcome(bot))
