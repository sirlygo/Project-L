"""Server-owner scheduling controls that work without the web dashboard."""

import time

import discord
from discord import app_commands
from discord.ext import commands

from config_loader import ConfigError
from guild_config import load_active_guild_config
from dashboard_store import cancel_announcement, schedule_announcement


class Scheduling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="scheduleannouncement", description="Schedule a one-time server announcement")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def schedule_announcement_command(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
        minutes_from_now: app_commands.Range[int, 1, 525600],
        message: app_commands.Range[str, 1, 1800],
    ):
        try:
            load_active_guild_config(interaction.guild_id)
        except ConfigError:
            await interaction.response.send_message("This server is not configured for Project L.", ephemeral=True)
            return
        if channel.guild.id != interaction.guild_id:
            await interaction.response.send_message("Select a channel in this server.", ephemeral=True)
            return
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message("I cannot send messages in that channel.", ephemeral=True)
            return
        announcement_id = schedule_announcement(
            interaction.guild_id, channel.id, interaction.user.id,
            message, int(time.time()) + minutes_from_now * 60,
        )
        await interaction.response.send_message(
            f"Scheduled announcement #{announcement_id} for {channel.mention} in "
            f"{minutes_from_now} minute(s). No users or roles will be pinged.", ephemeral=True,
        )

    @app_commands.command(name="cancelannouncement", description="Cancel a pending announcement")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancel_announcement_command(self, interaction: discord.Interaction, announcement_id: int):
        try:
            load_active_guild_config(interaction.guild_id)
        except ConfigError:
            await interaction.response.send_message("This server is not configured for Project L.", ephemeral=True)
            return
        cancelled = cancel_announcement(interaction.guild_id, announcement_id)
        await interaction.response.send_message(
            "Announcement cancelled." if cancelled else "That announcement is not pending.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Scheduling(bot))
