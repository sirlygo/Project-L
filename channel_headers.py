"""Idempotent, locally branded headers for Project L information channels."""

from hashlib import sha256

import discord

from branding import DEFAULT_RULES, resolve_art_path
from config_loader import load_config

SPECS = {
    "rules": ("rulesChannel", "📜 Server Rules", None),
    "announcements": ("announcementsChannel", "📢 Announcements", "Official server updates appear here."),
    "giveaways": ("giveawaysChannel", "🎁 Giveaways", "Watch this channel for new giveaways and winners."),
    "boosts": ("boostsChannel", "🚀 Server Boosts", "Thanks to everyone helping our community grow!"),
    "stream_alerts": ("alertsChannel", "📡 Stream Alerts", "Live stream notifications appear here."),
}


def header_copy(kind, config):
    title = config.get("branding", {}).get("headers", {}).get(kind, "")
    if not title:
        title = SPECS[kind][1]
    description = (
        config.get("branding", {}).get("rulesText", "").strip() or DEFAULT_RULES
        if kind == "rules" else SPECS[kind][2]
    )
    return str(title)[:256], str(description)[:4096]


def header_embed(kind, config):
    title, description = header_copy(kind, config)
    embed = discord.Embed(title=title, description=description, colour=0x65FF00)
    embed.set_footer(text=f"Project L • Channel Header • {kind}")
    path = resolve_art_path(kind, config)
    filename = None
    if path.is_file():
        digest = sha256(path.read_bytes()).hexdigest()[:10]
        filename = f"project_l_{kind}_{digest}{path.suffix.casefold()}"
        embed.set_image(url=f"attachment://{filename}")
    return embed, path, filename


async def ensure_channel_headers(bot, config=None):
    config = config if config is not None else load_config()
    guild = bot.get_guild(config["guildId"])
    if guild is None:
        return []
    managed = config.get("managedResources", {})
    outcomes = []
    for kind, (key, _title, _description) in SPECS.items():
        channel = guild.get_channel(int(managed.get(key, 0) or 0))
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            existing = None
            async for message in channel.history(limit=200):
                if message.author.id != bot.user.id or not message.embeds:
                    continue
                if message.embeds[0].footer.text == f"Project L • Channel Header • {kind}":
                    existing = message
                    break
            embed, path, filename = header_embed(kind, config)
            current = existing.embeds[0] if existing else None
            same_copy = bool(current and current.title == embed.title and current.description == embed.description)
            same_art = bool(
                current and (
                    (not filename and not current.image.url)
                    or (filename and filename in str(current.image.url or ""))
                )
            )
            if existing and same_copy and same_art:
                continue
            image_file = discord.File(path, filename=filename) if filename else None
            try:
                if existing:
                    if image_file:
                        await existing.edit(embed=embed, attachments=[image_file])
                    else:
                        await existing.edit(embed=embed, attachments=[])
                elif image_file:
                    await channel.send(embed=embed, file=image_file)
                else:
                    await channel.send(embed=embed)
            finally:
                if image_file:
                    image_file.close()
            outcomes.append(kind)
        except (OSError, discord.Forbidden, discord.HTTPException) as exc:
            print(f"[!] Could not install {kind} channel header: {exc}")
    return outcomes
