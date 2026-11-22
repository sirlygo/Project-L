"""Fail-closed slash-command boundary until every subsystem is guild-isolated."""

import discord
from discord import app_commands

from config_loader import load_config


def is_configured_guild(guild_id, config):
    return guild_id is not None and guild_id == config["guildId"]


class ConfiguredGuildTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_configured_guild(interaction.guild_id, load_config()):
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Project L has not been configured for this server yet.", ephemeral=True,
            )
        return False
