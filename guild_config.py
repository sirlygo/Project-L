"""Strict per-guild configuration lookup for the ongoing multi-server migration.

This module does not enable additional guilds in bot handlers. It deliberately
fails closed until those handlers and their data stores are tenant-aware.
"""

from pathlib import Path

from config_loader import BASE_DIR, ConfigError, load_config


GUILD_CONFIG_ROOT = BASE_DIR / "Data" / "guilds"
TENANT_DATABASES = {"users.db", "user.db", "levels.db", "dashboard.db"}


def guild_config_path(guild_id: int, *, root: Path = GUILD_CONFIG_ROOT) -> Path:
    if isinstance(guild_id, bool) or not isinstance(guild_id, int) or guild_id <= 0:
        raise ConfigError("Guild ID must be a positive integer.")
    return root / str(guild_id) / "config.json"


def load_guild_config(guild_id: int, *, root: Path = GUILD_CONFIG_ROOT,
                      primary_config=None) -> dict:
    primary = primary_config if primary_config is not None else load_config()
    if primary["guildId"] == guild_id:
        return primary
    path = guild_config_path(guild_id, root=root)
    if not path.is_file():
        raise ConfigError(f"Server {guild_id} is not configured for Project L.")
    config = load_config(path)
    if config["guildId"] != guild_id:
        raise ConfigError("Guild config ID does not match its directory.")
    if config["client_id"] != primary["client_id"]:
        raise ConfigError("Guild config belongs to a different Discord application.")
    # Credentials are application-wide. A server file cannot override them.
    for key in ("token", "twClientId", "twClientsecret"):
        config[key] = primary[key]
    return config


def guild_database_path(guild_id: int, database: str, *, root: Path = GUILD_CONFIG_ROOT,
                        primary_guild_id: int | None = None) -> Path:
    """Map tenant data to a private directory without moving legacy primary data."""
    guild_config_path(guild_id, root=root)  # Validate before constructing a path.
    if database not in TENANT_DATABASES:
        raise ConfigError("Unknown guild database name.")
    if guild_id == primary_guild_id:
        return root.parent / database
    return root / str(guild_id) / database
