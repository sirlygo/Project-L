"""Independent chat and voice participation levels with quiet milestones."""

import sqlite3
import time
from contextlib import closing

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config_loader import BASE_DIR, ConfigError
from guild_config import active_guild_configs, load_active_guild_config

DB_PATH = BASE_DIR / "Data" / "levels.db"
MILESTONES = (5, 15, 30)


def level_for_xp(xp):
    return int((max(0, xp) / 100) ** 0.5)


def add_xp(guild_id, member_id, track, amount, *, now=None):
    """Persist XP and return a newly reached milestone, or None."""
    if track not in ("chat", "voice"):
        raise ValueError("unknown XP track")
    timestamp = int(time.time() if now is None else now)
    with closing(sqlite3.connect(DB_PATH)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS levels (guild_id INTEGER NOT NULL, member_id INTEGER NOT NULL, "
            "chat_xp INTEGER NOT NULL DEFAULT 0, voice_xp INTEGER NOT NULL DEFAULT 0, "
            "last_chat INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, member_id))"
        )
        db.execute(
            "INSERT OR IGNORE INTO levels(guild_id, member_id) VALUES (?, ?)",
            (guild_id, member_id),
        )
        old_chat, old_voice, last_chat = db.execute(
            "SELECT chat_xp, voice_xp, last_chat FROM levels WHERE guild_id=? AND member_id=?",
            (guild_id, member_id),
        ).fetchone()
        if track == "chat" and timestamp - last_chat < 60:
            return None
        before = old_chat if track == "chat" else old_voice
        after = before + amount
        if track == "chat":
            db.execute(
                "UPDATE levels SET chat_xp=?, last_chat=? WHERE guild_id=? AND member_id=?",
                (after, timestamp, guild_id, member_id),
            )
        else:
            db.execute(
                "UPDATE levels SET voice_xp=? WHERE guild_id=? AND member_id=?",
                (after, guild_id, member_id),
            )
    old_level, new_level = level_for_xp(before), level_for_xp(after)
    return next((level for level in MILESTONES if old_level < level <= new_level), None)


def member_xp(guild_id, member_id):
    with closing(sqlite3.connect(DB_PATH)) as db:
        row = db.execute(
            "SELECT chat_xp, voice_xp FROM levels WHERE guild_id=? AND member_id=?",
            (guild_id, member_id),
        ).fetchone()
    return row or (0, 0)


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(DB_PATH)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS levels (guild_id INTEGER NOT NULL, member_id INTEGER NOT NULL, "
                "chat_xp INTEGER NOT NULL DEFAULT 0, voice_xp INTEGER NOT NULL DEFAULT 0, "
                "last_chat INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, member_id))"
            )
        self.voice_xp_tick.start()

    def cog_unload(self):
        self.voice_xp_tick.cancel()

    async def announce(self, member, track, milestone, config):
        await self.ensure_milestone_roles(member, track, milestone, config)
        channel_id = config.get("managedResources", {}).get("xpChannel", 0)
        channel = member.guild.get_channel(int(channel_id or 0))
        if channel:
            try:
                await channel.send(
                    f"✨ {member.mention} reached **{track.title()} Level {milestone}**! "
                    "Use `/rank` to see your progress."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def ensure_milestone_roles(self, member, track, level, config):
        """Higher levels keep every previously unlocked lounge role."""
        role_ids = config.get("managedResources", {}).get("levelRoles", {}).get(track, {})
        missing = [
            role for milestone in (5, 15, 30)
            if level >= milestone
            for role in [member.guild.get_role(int(role_ids.get(str(milestone), 0) or 0))]
            if role is not None and role not in member.roles
        ]
        if missing:
            try:
                await member.add_roles(*missing, reason=f"Project L {track} level {level}")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or len(message.content.strip()) < 8:
            return
        if message.content.startswith(("/", "!")):
            return
        try:
            config = load_active_guild_config(message.guild.id)
        except ConfigError:
            return
        milestone = add_xp(message.guild.id, message.author.id, "chat", 20)
        if milestone:
            await self.announce(message.author, "chat", milestone, config)

    @tasks.loop(minutes=1)
    async def voice_xp_tick(self):
        for guild, config in active_guild_configs(self.bot.guilds):
            for channel in guild.voice_channels:
                eligible = [
                    member for member in channel.members
                    if not member.bot and member.voice and not (
                        member.voice.self_mute or member.voice.mute
                        or member.voice.self_deaf or member.voice.deaf
                    ) and channel != guild.afk_channel
                ]
                if len(eligible) < 2:
                    continue
                for member in eligible:
                    milestone = add_xp(guild.id, member.id, "voice", 10)
                    if milestone:
                        await self.announce(member, "voice", milestone, config)

    @voice_xp_tick.before_loop
    async def before_voice_xp_tick(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="rank", description="Show your chat and voice XP levels")
    async def rank(self, interaction: discord.Interaction):
        try:
            config = load_active_guild_config(interaction.guild_id)
        except ConfigError:
            await interaction.response.send_message("This command is only available in the configured server.", ephemeral=True)
            return
        chat, voice = member_xp(interaction.guild_id, interaction.user.id)
        await self.ensure_milestone_roles(
            interaction.user, "chat", level_for_xp(chat), config,
        )
        await self.ensure_milestone_roles(
            interaction.user, "voice", level_for_xp(voice), config,
        )
        await interaction.response.send_message(
            f"Chat: **Level {level_for_xp(chat)}** ({chat} XP)\n"
            f"Voice: **Level {level_for_xp(voice)}** ({voice} XP)\n"
            "Milestone roles unlock at levels 5, 15, and 30. XP updates are quiet between milestones.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Leveling(bot))
