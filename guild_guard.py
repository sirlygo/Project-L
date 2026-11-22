"""Fail-closed slash-command boundary until every subsystem is guild-isolated."""

import discord
from discord import app_commands

from config_loader import ConfigError, load_config
from guild_config import load_active_guild_config


def is_configured_guild(guild_id, config):
    return guild_id is not None and guild_id == config["guildId"]


class ConfiguredGuildTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is not None:
            try:
                load_active_guild_config(interaction.guild_id)
                return True
            except ConfigError:
                pass
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Project L has not been configured for this server yet.", ephemeral=True,
            )
        return False
