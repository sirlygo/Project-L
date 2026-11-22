"""Named private voice rooms created from the managed button panel."""

import sqlite3

import discord

from config_loader import BASE_DIR, ConfigError, load_config
from guild_config import load_active_guild_config
from Commands.public_voice import clean_room_name

DB_PATH = BASE_DIR / "Data" / "users.db"


def ensure_private_voice_table(db, primary_guild_id):
    db.execute(
        "CREATE TABLE IF NOT EXISTS private_voice_rooms ("
        "guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, "
        "channel_id INTEGER NOT NULL, PRIMARY KEY(guild_id,owner_id))"
    )
    has_legacy = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if has_legacy:
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "voice" in columns:
            db.execute(
                "INSERT OR IGNORE INTO private_voice_rooms(guild_id,owner_id,channel_id) "
                "SELECT ?,userid,voice FROM users WHERE voice IS NOT NULL AND voice>0",
                (primary_guild_id,),
            )


def private_room_for_owner(db, guild_id, owner_id):
    return db.execute(
        "SELECT channel_id FROM private_voice_rooms WHERE guild_id=? AND owner_id=?",
        (guild_id, owner_id),
    ).fetchone()


class PrivateVoiceNameModal(discord.ui.Modal, title="Create a private voice chat"):
    room_name = discord.ui.TextInput(
        label="Room name", placeholder="My private game room", max_length=80,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        try:
            config = load_active_guild_config(guild.id if guild else None)
        except ConfigError:
            await interaction.response.send_message("Use this in the configured server.", ephemeral=True)
            return
        member = interaction.user
        streamer = guild.get_role(int(config.get("streamRole", 0) or 0))
        if streamer is None or streamer not in member.roles:
            await interaction.response.send_message(
                "You need the streamer role to create a private voice chat.", ephemeral=True,
            )
            return
        category = guild.get_channel(int(config.get("voicecategory", 0) or 0))
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "The private voice category is unavailable. Ask staff to rerun setup.", ephemeral=True,
            )
            return
        try:
            name = clean_room_name(self.room_name.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        with sqlite3.connect(DB_PATH) as db:
            ensure_private_voice_table(db, load_config()["guildId"])
            existing = private_room_for_owner(db, guild.id, member.id)
        if existing and existing[0]:
            channel = guild.get_channel(int(existing[0]))
            if channel is not None:
                await interaction.response.send_message(
                    f"You already have a private voice chat: {channel.mention}", ephemeral=True,
                )
                return
        room = None
        try:
            room = await guild.create_voice_channel(
                name=name, category=category,
                reason=f"Private voice chat created by {member.id}",
            )
            await room.set_permissions(
                member, view_channel=True, manage_channels=True,
                connect=True, speak=True,
            )
            with sqlite3.connect(DB_PATH) as db:
                ensure_private_voice_table(db, load_config()["guildId"])
                db.execute(
                    "INSERT INTO private_voice_rooms(guild_id,owner_id,channel_id) VALUES(?,?,?) "
                    "ON CONFLICT(guild_id,owner_id) DO UPDATE SET channel_id=excluded.channel_id",
                    (guild.id, member.id, room.id),
                )
                # Keep the primary server's legacy field synchronized for older releases.
                if guild.id == load_config()["guildId"]:
                    db.execute("UPDATE users SET voice=? WHERE userid=?", (room.id, member.id))
        except (discord.Forbidden, discord.HTTPException, sqlite3.Error) as exc:
            if room is not None:
                try:
                    await room.delete(reason="Private room setup failed")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            print(f"[!] Could not create private voice chat: {exc}")
            await interaction.response.send_message(
                "I could not create that private voice chat. Ask staff to check Manage Channels.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Your private voice chat is ready: {room.mention}", ephemeral=True,
        )


async def setup(_bot):
    """Expose the modal module to the extension loader."""
