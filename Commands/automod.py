"""Optional, conservative anti-spam and invite-link filtering."""

from collections import defaultdict, deque
from datetime import timedelta
import re
import time

import discord
from discord.ext import commands

from config_loader import load_config
from dashboard_store import safe_record_case

INVITE_LINK = re.compile(r"https?://(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.I)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recent = defaultdict(deque)
        self.last_notice = {}
        self.join_times = defaultdict(deque)
        self.last_raid_alert = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        config = load_config()
        if message.guild.id != config["guildId"]:
            return
        settings = config.get("moderation") or {}
        if not any(settings.get(key) for key in ("antiSpamEnabled", "blockInviteLinks")):
            return
        perms = message.author.guild_permissions
        if perms.administrator or perms.manage_messages:
            return
        blocked = bool(settings.get("blockInviteLinks") and INVITE_LINK.search(message.content))
        if settings.get("antiSpamEnabled"):
            now = time.monotonic()
            key = (message.guild.id, message.author.id)
            recent = self.recent[key]
            window = max(2, min(120, int(settings.get("spamWindowSeconds", 10))))
            limit = max(2, min(30, int(settings.get("spamLimit", 5))))
            while recent and now - recent[0] > window:
                recent.popleft()
            recent.append(now)
            blocked = blocked or len(recent) > limit
        if not blocked:
            return
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return
        now = time.monotonic()
        if now - self.last_notice.get(message.author.id, 0) >= 60:
            self.last_notice[message.author.id] = now
            try:
                await message.author.send(
                    "Project L removed your message because it matched an enabled server safety filter."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = load_config()
        if member.guild.id != config["guildId"]:
            return
        settings = config.get("moderation") or {}
        if not settings.get("raidEnabled") or member.bot:
            return
        now = time.monotonic()
        guild_id = member.guild.id
        window = max(5, min(300, int(settings.get("raidWindowSeconds", 30))))
        limit = max(3, min(100, int(settings.get("raidJoinLimit", 8))))
        joins = self.join_times[guild_id]
        while joins and now - joins[0] > window:
            joins.popleft()
        joins.append(now)
        if len(joins) < limit:
            return
        if now - self.last_raid_alert.get(guild_id, 0) >= window:
            self.last_raid_alert[guild_id] = now
            logs_id = int(config.get("logs", 0) or 0)
            channel = member.guild.get_channel(logs_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(
                        f"⚠️ Possible join raid: {len(joins)} members joined in "
                        f"{window} seconds. Review recent joins.",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
        if settings.get("raidAction") == "timeout":
            try:
                await member.timeout(
                    discord.utils.utcnow() + timedelta(minutes=10),
                    reason="Project L raid protection",
                )
                safe_record_case(guild_id, member.id, self.bot.user.id, "raid_timeout", "Join burst")
            except (discord.Forbidden, discord.HTTPException):
                pass


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
