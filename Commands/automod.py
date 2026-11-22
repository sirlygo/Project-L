"""Optional, conservative anti-spam and invite-link filtering."""

from collections import defaultdict, deque
import re
import time

import discord
from discord.ext import commands

from config_loader import load_config

INVITE_LINK = re.compile(r"https?://(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.I)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recent = defaultdict(deque)
        self.last_notice = {}

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
            while recent and now - recent[0] > 10:
                recent.popleft()
            recent.append(now)
            blocked = blocked or len(recent) > 5
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


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
