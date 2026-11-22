"""User-named public voice rooms with safe empty-room cleanup."""

import sqlite3
import time
from contextlib import closing

import discord
from discord.ext import commands, tasks

from config_loader import BASE_DIR, ConfigError, load_config
from guild_config import load_active_guild_config

DB_PATH = BASE_DIR / "Data" / "users.db"


def _connect():
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "CREATE TABLE IF NOT EXISTS public_voice_rooms ("
        "channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, "
        "owner_id INTEGER NOT NULL, created_at INTEGER NOT NULL)"
    )
    return db


def room_for_owner(guild_id, owner_id):
    with closing(_connect()) as db:
        return db.execute(
            "SELECT channel_id FROM public_voice_rooms WHERE guild_id=? AND owner_id=?",
            (guild_id, owner_id),
        ).fetchone()


def tracked_room(channel_id):
    with closing(_connect()) as db:
        return db.execute(
            "SELECT guild_id, owner_id, created_at FROM public_voice_rooms WHERE channel_id=?",
            (channel_id,),
        ).fetchone()


def remember_room(channel_id, guild_id, owner_id):
    with closing(_connect()) as db, db:
        db.execute(
            "INSERT OR REPLACE INTO public_voice_rooms(channel_id,guild_id,owner_id,created_at) "
            "VALUES(?,?,?,?)", (channel_id, guild_id, owner_id, int(time.time())),
        )


def forget_room(channel_id):
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM public_voice_rooms WHERE channel_id=?", (channel_id,))


def old_empty_rooms(cutoff):
    with closing(_connect()) as db:
        return db.execute(
            "SELECT channel_id,guild_id FROM public_voice_rooms WHERE created_at<=?",
            (cutoff,),
        ).fetchall()


def clean_room_name(value):
    name = " ".join(str(value).split())[:80]
    if not name or any(ord(character) < 32 for character in name):
        raise ValueError("Enter a room name.")
    return name


class PublicVoiceNameModal(discord.ui.Modal, title="Create a public voice chat"):
    room_name = discord.ui.TextInput(
        label="Room name", placeholder="Game night voice chat", max_length=80,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            config = load_active_guild_config(interaction.guild_id)
        except ConfigError:
            await interaction.response.send_message("Use this in the configured server.", ephemeral=True)
            return
        member = interaction.user
        verified = interaction.guild.get_role(config["verified"])
        if verified not in member.roles and not member.guild_permissions.administrator:
            await interaction.response.send_message("Verify before creating a voice chat.", ephemeral=True)
            return
        category_id = config.get("managedResources", {}).get("publicVoiceCategory", 0)
        category = interaction.guild.get_channel(int(category_id or 0))
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("The public voice category is unavailable. Ask staff to rerun setup.", ephemeral=True)
            return
        previous = room_for_owner(interaction.guild_id, member.id)
        if previous:
            existing = interaction.guild.get_channel(previous[0])
            if existing:
                await interaction.response.send_message(
                    f"You already have a public voice chat: {existing.mention}", ephemeral=True,
                )
                return
            forget_room(previous[0])
        room = None
        try:
            name = clean_room_name(self.room_name.value)
            room = await interaction.guild.create_voice_channel(
                name=name, category=category,
                reason=f"Public voice chat created by {member.id}",
            )
            remember_room(room.id, interaction.guild_id, member.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except (discord.Forbidden, discord.HTTPException, sqlite3.Error) as exc:
            if room is not None:
                try:
                    await room.delete(reason="Public voice room could not be tracked")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            print(f"[!] Could not create public voice chat: {exc}")
            await interaction.response.send_message(
                "I could not create the voice chat. Ask staff to check Manage Channels.", ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Your public voice chat is ready: {room.mention}. Join within two minutes; "
            "it will be removed when empty.", ephemeral=True,
        )


class PublicVoiceCleanup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with closing(_connect()):
            pass
        self.sweep_empty_rooms.start()

    def cog_unload(self):
        self.sweep_empty_rooms.cancel()

    async def delete_if_empty(self, room):
        if room.members or not tracked_room(room.id):
            return
        try:
            await room.delete(reason="Temporary public voice chat is empty")
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[!] Could not remove empty public voice chat {room.id}: {exc}")
            return
        forget_room(room.id)

    async def retire_legacy_public_channel(self):
        """Remove only the old managed fixed room once the replacement is live."""
        config = load_config()
        managed = config.get("managedResources", {})
        old_id = int(managed.get("publicVoiceChannel", 0) or 0)
        panel_id = int(managed.get("publicVoicePanelChannel", 0) or 0)
        guild = self.bot.get_guild(config["guildId"])
        if not guild or not old_id or not panel_id:
            return
        panel = guild.get_channel(panel_id)
        room = guild.get_channel(old_id)
        if not isinstance(panel, discord.TextChannel) or not isinstance(room, discord.VoiceChannel):
            return
        if room.name != "Custom Voice Chat" or room.members:
            return
        try:
            async for message in panel.history(limit=30):
                if message.author.id != self.bot.user.id:
                    continue
                if any(
                    getattr(component, "custom_id", None) == "publicvoicecreate"
                    for row in message.components for component in getattr(row, "children", ())
                ):
                    await room.delete(reason="Replaced by public voice creation panel")
                    print("[OK] Retired the old fixed Custom Voice Chat channel.")
                    return
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[!] Could not retire old public voice channel {old_id}: {exc}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, _member, before, after):
        room = before.channel
        if room is not None and room != after.channel and tracked_room(room.id):
            await self.delete_if_empty(room)

    @tasks.loop(minutes=1)
    async def sweep_empty_rooms(self):
        await self.retire_legacy_public_channel()
        for channel_id, guild_id in old_empty_rooms(int(time.time()) - 120):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            room = guild.get_channel(channel_id)
            if room is None:
                forget_room(channel_id)
            elif isinstance(room, discord.VoiceChannel):
                await self.delete_if_empty(room)

    @sweep_empty_rooms.before_loop
    async def before_sweep(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(PublicVoiceCleanup(bot))
