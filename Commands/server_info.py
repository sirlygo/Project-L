"""Small, predictable answers and server boost acknowledgements."""

import discord
from discord.ext import commands

from config_loader import load_config
from discord_provisioning import build_bot_invite_url


def answer_question(text, client_id, guild_id):
    question = " ".join(text.casefold().split())
    if "tell me about project l" in question or "what is project l" in question:
        return (
            "Project L is this server's bot for verification, self-roles, help tickets, "
            "private voice, music, events, and community features. Try `/help` for commands."
        )
    if "how can i get this in my server" in question or "invite project l" in question:
        return (
            "Invite Project L with this link, enable Presence, Server Members, and "
            "Message Content intents in the Discord Developer Portal, then run the "
            "included setup wizard: " + build_bot_invite_url(client_id, guild_id)
        )
    return None


class ServerInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or self.bot.user not in message.mentions:
            return
        config = load_config()
        if message.guild.id != config["guildId"]:
            return
        answer = answer_question(message.content, config["client_id"], 0)
        if answer:
            try:
                await message.reply(answer, mention_author=False)
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.premium_since is not None or after.premium_since is None:
            return
        config = load_config()
        if after.guild.id != config["guildId"]:
            return
        channel_id = config.get("managedResources", {}).get("boostsChannel", 0)
        channel = after.guild.get_channel(channel_id)
        if channel:
            try:
                await channel.send(f"🚀 Thank you {after.mention} for boosting the server!")
            except (discord.Forbidden, discord.HTTPException):
                pass


async def setup(bot):
    await bot.add_cog(ServerInfo(bot))
