"""Named private voice rooms created from the managed button panel."""

import sqlite3

import discord

from config_loader import BASE_DIR, load_config
from Commands.public_voice import clean_room_name

DB_PATH = BASE_DIR / "Data" / "users.db"


class PrivateVoiceNameModal(discord.ui.Modal, title="Create a private voice chat"):
    room_name = discord.ui.TextInput(
        label="Room name", placeholder="My private game room", max_length=80,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        config = load_config()
        guild = interaction.guild
        if guild is None or guild.id != config["guildId"]:
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
            existing = db.execute("SELECT voice FROM users WHERE userid=?", (member.id,)).fetchone()
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
                db.execute(
                    "INSERT OR IGNORE INTO users(userid,balance,invited,left) VALUES(?,0,0,0)",
                    (member.id,),
                )
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
