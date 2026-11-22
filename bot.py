import json
import discord
from discord.ext import commands, tasks
import asyncio
import os
import sys
import time
import datetime
import sqlite3
import random
import requests
from collections import deque
from contextlib import closing
from easy_pil import Editor, load_image_async, Font
from Commands.members import mAddBtn, role_button_db_path
from Commands.panels import ensure_automatic_panels
from Commands.giveaways import giveaway_path
from channel_headers import ensure_channel_headers
from dashboard_web import start_dashboard
from guild_guard import ConfiguredGuildTree
from guild_config import active_guild_configs, guild_config_path, load_active_guild_config
from dashboard_store import (
    claim_due_announcements, finish_announcement, mark_interrupted_announcements_failed,
    mark_response_alerted,
    overdue_tickets, purge_transcripts,
)
from config_loader import (
    BASE_DIR,
    ConfigError,
    configuration_warnings,
    load_config,
    load_role_ids,
    missing_required_settings,
)
from youtube_notifications import fetch_recent_youtube_content
from giveaway_utils import chunk_display_values, ended_description, parse_winner_count
from command_errors import app_command_error_message
from twitch_notifications import (
    TwitchTokenCache,
    load_notified_stream_ids,
    remember_notified_stream,
)
import traceback


os.chdir(BASE_DIR)

try:
    config = load_config()
except ConfigError as exc:
    print(f"[!] Configuration error: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

token = config["token"]
guildId = config["guildId"]
verifiedRoleId = config["verified"]
kickMemberFunction = config["kickMemberFunction"]
welcomeid = config.get("managedResources", {}).get("welcomeMessagesChannel") or config["welcome"]
botclientid = config["client_id"]
youtubeid = config["ytChannelId"]
twitchid = config["twChannelId"]
modmailid = config["modmail"]
ytchannel = config["ytChannel"]
twchannel = config["twitchChannelName"]
serverStats = config["serverStatChannelIds"]
clientid = config["twClientId"]
streamRole = config["streamRole"]
streamPingRole = int(
    config.get("managedResources", {}).get("selfRoles", {}).get("pings", {}).get("Now Streaming Pings", 0)
    or 0
)
clientsecret = config["twClientsecret"]
friend = config["friendTwitch"]

previous = {}
notified = set()
notified_order = deque()
twitch_token_cache = TwitchTokenCache()
youtube_cache_primed = set()
youtube_last_error = None
youtube_last_error_time = 0.0


def fetch_youtube_content(limit, source=None):
    """Fetch recent channel entries away from the Discord event loop."""
    return fetch_recent_youtube_content(source or ytchannel, limit)


def report_youtube_failure(context, exc):
    """Rate-limit repeated poll errors while retaining an actionable reason."""
    global youtube_last_error, youtube_last_error_time
    message = f"{type(exc).__name__}: {exc}"
    now = time.monotonic()
    if message != youtube_last_error or now - youtube_last_error_time >= 1800:
        print(f"[!] YouTube {context} failed; will retry later: {message}")
        youtube_last_error = message
        youtube_last_error_time = now


def mark_youtube_success():
    global youtube_last_error, youtube_last_error_time
    if youtube_last_error is not None:
        print("[OK] YouTube notifications recovered.")
    youtube_last_error = None
    youtube_last_error_time = 0.0


intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

client = commands.Bot(
    command_prefix="!",
    tree_cls=ConfiguredGuildTree,
    intents=intents,
    help_command=None,
    status=discord.Status.online,
    activity=discord.Activity(type=discord.ActivityType.playing, name="/help"),
    application_id=botclientid or None,
)


async def sticky_ready(id, content, limit):
    @tasks.loop(seconds=12)
    async def stickyloop(channel: discord.TextChannel, sticky_object: dict):
        message, message_limit = sticky_object["content"], sticky_object["messageLimit"]
        # print(message)
        if channel.id not in client.sticky:
            print("channel not found")
            stickyloop.stop()
            return
        elif client.sticky[channel.id]["content"] != message:
            print("stopping loop")
            stickyloop.stop()
            return

        try:
            msgz = []
            async for msg in channel.history(limit=message_limit, oldest_first=False):
                msgz.append(msg.content)

            if message not in msgz:
                await channel.send(f"{message}")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            print(f"[!] Sticky update failed for channel {channel.id}: {exc}")

    sticky_object = {"content": content, "messageLimit": limit}
    # print(sticky_object)
    client.sticky[id] = sticky_object
    c = client.get_channel(id)
    if c is None:
        try:
            c = await client.fetch_channel(id)
        except discord.NotFound:
            client.sticky.pop(id, None)
            return "missing"
        except discord.Forbidden:
            client.sticky.pop(id, None)
            return "forbidden"
        except discord.HTTPException:
            client.sticky.pop(id, None)
            return "unavailable"
    channel_guild = getattr(c, "guild", None)
    try:
        if channel_guild is None:
            raise ConfigError("Sticky channel has no server.")
        load_active_guild_config(channel_guild.id)
    except ConfigError:
        client.sticky.pop(id, None)
        return "wrong_server"
    if not hasattr(c, "history") or not hasattr(c, "send"):
        client.sticky.pop(id, None)
        return "unsupported"
    stickyloop.start(c, sticky_object)
    return None


channelName = {
    "totalMembers": "👥〢Members",
    "totalBots": "🤖〢Bots",
    "totalBoosts": "🚀〢ʙᴏᴏsᴛs",
    "onlineMembers": "🟢〢Online",
    "offlineMembers": "🔴〢Offline",
}


@tasks.loop(minutes=6)  # Set the interval to 5 minutes
async def update_stats():
    for guild, guild_config in active_guild_configs(client.guilds):
        stat_channels = guild_config.get("serverStatChannelIds", {})
        if not any(stat_channels.values()):
            continue
        totalMembers = guild.member_count
        totalBoosts = guild.premium_subscription_count
        totalBots = sum(1 for member in guild.members if member.bot)
        onlineMembers = sum(
            1 for member in guild.members if member.status == discord.Status.online
        )
        offlineMembers = totalMembers - onlineMembers

        # print(totalMembers)
        # print(totalBoosts)
        # print(totalBots)
        # print(onlineMembers)
        # print(offlineMembers)
        # print(serverStats.items())

        for stat_key, channel_id in stat_channels.items():
            if not channel_id:
                continue
            try:
                channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)

                if channel and getattr(getattr(channel, "guild", None), "id", guild.id) == guild.id:
                    stat_value = locals()[stat_key]
                    channel_name = channelName.get(
                        stat_key, "Unknown"
                    )  # Get the corresponding channel name
                    # print('before the end')
                    # print(f'{channel_name} {stat_value}')
                    desired_name = f"{channel_name} {stat_value}"
                    if channel.name != desired_name:
                        await channel.edit(name=desired_name)
                    # print('hey i reached the end')
                else:
                    print(f"Channel not found for {stat_key}.")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                print(f"Could not update {stat_key} channel {channel_id}: {exc}")


def member_cleanup_date_path(guild_id):
    return BASE_DIR / "date.json" if guild_id == guildId else guild_config_path(guild_id).with_name("cleanup-date.json")


def read_last_date(path=None):
    """Read the cleanup watermark, recreating a missing or malformed file."""
    path = path or BASE_DIR / "date.json"
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        last_date_str = data.get("lastDate") if isinstance(data, dict) else None
        if last_date_str:
            return datetime.datetime.fromisoformat(last_date_str)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[!] Resetting invalid member-cleanup date file: {exc}")

    initial_date = datetime.datetime.utcnow()
    write_last_date(initial_date, path)
    return initial_date


def write_last_date(last_date, path=None):
    path = path or BASE_DIR / "date.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"lastDate": last_date.isoformat()}, file)


@tasks.loop(minutes=59)
async def check_members_task():
    for guild, guild_config in active_guild_configs(client.guilds):
        if guild_config.get("kickMemberFunction"):
            await check_guild_members(guild, guild_config)


async def check_guild_members(guild, guild_config):
    """Apply the explicitly enabled cleanup policy within one server only."""
    try:
        current_time = datetime.datetime.utcnow()
        date_path = member_cleanup_date_path(guild.id)
        last_date = read_last_date(date_path)

        if (current_time - last_date).days <= 30:
            return
        verified_role = discord.utils.get(guild.roles, id=guild_config["verified"])
        if verified_role is None:
            print("Verified role not found in the guild.")
            return

        cutoff = discord.utils.utcnow() - datetime.timedelta(days=30)
        async for member in guild.fetch_members():
            try:
                joined_at = member.joined_at
                should_kick = (
                    not member.bot
                    and member.id not in (guild.owner_id, client.user.id)
                    and verified_role not in member.roles
                    and joined_at is not None
                    and joined_at <= cutoff
                )
                if should_kick:
                    await member.kick(reason="Inactive and not verified")
                    await asyncio.sleep(30)
            except discord.Forbidden:
                print(
                    f"Skipping kick for {member} (role hierarchy or permission denied)"
                )
            except (discord.HTTPException, OSError) as exc:
                print(f"Could not process member {member}: {exc}")
        write_last_date(current_time, date_path)
    except Exception as exc:
        # Keep the recurring loop alive if Discord or the watermark file fails.
        print(f"[!] Member cleanup check failed in {guild.id}; will retry later: {exc}")


# @client.event
# async def on_guild_channel_update(before, after):
#     print('sexs')
@client.event
async def on_error(event, *args, **kwargs):
    error_message = traceback.format_exc()
    print(f"Error in event {event}: {error_message}")


@client.event
async def on_ready():

    print(
        f"[!] {time.strftime('%Y-%m-%d - %H:%M')}: Initiating bot. Please wait...",
        end="",
        flush=True,
    )
    # while not youtubeloop.is_running() or not twitchloop.is_running() or not checker.is_running():
    #     await asyncio.sleep(1)

    print("\n[!] Bot is online")
    print(f"[!] Logged in as: {client.user} - {client.user.id}")
    if not client.persistent_state_loaded:
        with sqlite3.connect(BASE_DIR / "sticky.db") as conn:
            values = conn.execute("SELECT * FROM infos_salos").fetchall()
        skipped_stickies = 0
        for row in values:
            if row[1]:
                reason = await sticky_ready(row[0], row[1], row[2])
                if reason is not None:
                    skipped_stickies += 1
        if skipped_stickies:
            print(
                f"[!] Skipped {skipped_stickies} saved sticky message(s) that are "
                "missing, inaccessible, or from another server."
            )

        client.persistent_state_loaded = True

    for guild, _guild_config in active_guild_configs(client.guilds):
        restore_role_buttons_for_guild(guild)

    for guild, _guild_config in active_guild_configs(client.guilds):
        await restore_twitch_state_for_guild(guild)

    for guild, guild_config in active_guild_configs(client.guilds):
        await reconcile_managed_guild(guild, guild_config)

    if not update_stats.is_running():
        update_stats.start()

    if any(c.get("kickMemberFunction") and c.get("verified") for _, c in active_guild_configs(client.guilds)) and not check_members_task.is_running():
        check_members_task.start()

    if any(c.get("ytChannel") and c.get("ytChannelId") for _, c in active_guild_configs(client.guilds)) and not youtubeloop.is_running():
        youtubeloop.start()

    twitch_enabled = clientid and clientsecret and any(
        (c.get("twitchChannelName") and c.get("twChannelId")) or c.get("friendTwitch")
        for _, c in active_guild_configs(client.guilds)
    )
    if twitch_enabled and not twitchloop.is_running():
        twitchloop.start()

    if not checker.is_running():
        checker.start()

    if not ticket_maintenance.is_running():
        ticket_maintenance.start()
    if not announcement_scheduler.is_running():
        for guild, _guild_config in active_guild_configs(client.guilds):
            interrupted = await asyncio.to_thread(mark_interrupted_announcements_failed, guild.id)
            if interrupted:
                print(f"[!] {interrupted} interrupted announcement(s) in {guild.id} marked failed.")
        announcement_scheduler.start()

    if not client.dashboard_attempted:
        client.dashboard_attempted = True
        try:
            client.dashboard_server = await start_dashboard(client)
        except (OSError, ValueError) as exc:
            print(f"[!] Browser dashboard could not start: {exc}")


async def reconcile_managed_guild(guild, guild_config):
    """Install managed messages and layout using only this server's resources."""
    if guild.id not in client.panels_reconciled:
        panel_report = await ensure_automatic_panels(client, guild_config)
        if panel_report.created:
            print(f"[OK] Installed panels in {guild.id}: " + ", ".join(panel_report.created))
        if panel_report.updated:
            print(f"[OK] Updated panels in {guild.id}: " + ", ".join(panel_report.updated))
        if panel_report.moved:
            print(f"[OK] Moved panels in {guild.id}: " + ", ".join(panel_report.moved))
        if panel_report.failed:
            print(f"[!] Panel setup in {guild.id} needs attention: " + "; ".join(panel_report.failed))
        else:
            client.panels_reconciled.add(guild.id)

    if guild.id not in client.headers_reconciled:
        installed_headers = await ensure_channel_headers(client, guild_config)
        if installed_headers:
            print(f"[OK] Installed channel headers in {guild.id}: " + ", ".join(installed_headers))
        client.headers_reconciled.add(guild.id)

    if guild.id not in client.layout_reconciled:
        managed = guild_config.get("managedResources", {})
        category_order = (
            "statsCategory", "informationCategory", "announcementsCategory",
            "communityCategory", "selfRolesCategory", "helpCategory",
            "voiceHubCategory", "publicVoiceCategory",
            "voicecategory", "staffCategory", "modmail",
        )
        ordered_ids = [
            int(guild_config.get(key, 0) if key in ("modmail", "voicecategory") else managed.get(key, 0) or 0)
            for key in category_order
        ]
        ordered_ids.extend(int(guild_config.get("tickets", {}).get(key, 0) or 0) for key in (
            "category_help", "category_suggestions", "category_report"
        ))
        all_positioned = True
        for position, category_id in enumerate(ordered_ids):
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                all_positioned = False
                continue
            if category.position == position:
                continue
            try:
                await category.edit(position=position, reason="Organize Project L server categories")
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"[!] Could not position category {category_id}: {exc}")
                all_positioned = False
        general_id = int(managed.get("generalChatChannel", 0) or 0)
        general = guild.get_channel(general_id)
        if isinstance(general, discord.TextChannel) and general.position != 0:
            try:
                await general.edit(position=0, reason="Keep general chat first in Community")
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"[!] Could not position general chat: {exc}")
                all_positioned = False
        if all_positioned:
            client.layout_reconciled.add(guild.id)


def restore_role_buttons_for_guild(guild):
    if guild.id in client.restored_role_guilds:
        return
    with closing(sqlite3.connect(role_button_db_path(guild.id))) as conn:
        values = conn.execute("SELECT * FROM roles").fetchall()
    for row in values:
        try:
            client.add_view(
                mAddBtn(
                    content=row[4], emoji=row[3], role=discord.Object(id=row[2]),
                    custom_id=row[5],
                ),
                message_id=int(row[1]),
            )
        except Exception as exc:
            print(f"[!] Could not restore a role button in {guild.id}: {exc}")
    client.restored_role_guilds.add(guild.id)


async def restore_twitch_state_for_guild(guild):
    if guild.id in client.twitch_state_loaded:
        return
    try:
        retained_streams = await asyncio.to_thread(
            load_notified_stream_ids, giveaway_path(guild.id),
        )
        keys = [(guild.id, stream_id) for stream_id in retained_streams]
        notified.update(keys)
        notified_order.extend(keys)
        print(f"[OK] Restored {len(keys)} Twitch notification ID(s) in {guild.id}.")
        client.twitch_state_loaded.add(guild.id)
    except (OSError, sqlite3.Error) as exc:
        print(f"[!] Could not restore Twitch notification state in {guild.id}: {exc}")


@tasks.loop(seconds=30)
async def announcement_scheduler():
    for guild, _guild_config in active_guild_configs(client.guilds):
        for announcement in await asyncio.to_thread(claim_due_announcements, guild.id):
            channel = guild.get_channel(announcement["channel_id"])
            sent = False
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(
                        announcement["content"], allowed_mentions=discord.AllowedMentions.none(),
                    )
                    sent = True
                except (discord.Forbidden, discord.HTTPException):
                    pass
            await asyncio.to_thread(finish_announcement, guild.id, announcement["id"], sent)


@tasks.loop(minutes=10)
async def ticket_maintenance():
    for guild, guild_config in active_guild_configs(client.guilds):
        settings = guild_config.get("ticketWorkspace") or {}
        retention_days = int(settings.get("transcriptRetentionDays", 0) or 0)
        if retention_days > 0:
            removed = await asyncio.to_thread(
                purge_transcripts, guild.id, int(time.time()) - retention_days * 86400,
            )
            if removed:
                print(f"[OK] Purged {removed} expired ticket transcript(s) in {guild.id}.")
        target = int(settings.get("responseTargetMinutes", 0) or 0)
        if target <= 0:
            continue
        alert_channel = guild.get_channel(int(guild_config.get("logs", 0) or 0))
        if not isinstance(alert_channel, discord.TextChannel):
            continue
        for ticket in await asyncio.to_thread(overdue_tickets, guild.id, target):
            try:
                await alert_channel.send(
                    f"⚠️ Ticket <#{ticket['channel_id']}> has no staff response after "
                    f"{target} minutes.", allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException):
                break
            await asyncio.to_thread(mark_response_alerted, guild.id, ticket["channel_id"])


def update_giveaway_record(giveaway_id, guild_id, *, delete=False):
    try:
        with closing(sqlite3.connect(giveaway_path(guild_id))) as conn, conn:
            if delete:
                conn.execute("DELETE FROM giveaways WHERE id = ?", (giveaway_id,))
            else:
                conn.execute(
                    "UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,)
                )
        return True
    except sqlite3.Error as exc:
        print(f"[!] Could not update giveaway {giveaway_id}: {exc}")
        return False


@tasks.loop(seconds=30)
async def checker():
    for guild, _guild_config in active_guild_configs(client.guilds):
        await check_guild_giveaways(guild)


async def check_guild_giveaways(guild):
    guild_id = guild.id
    try:
        with closing(sqlite3.connect(giveaway_path(guild_id))) as conn:
            records = conn.execute(
                "SELECT id, channel, message FROM giveaways "
                "WHERE ends <= ? AND ended = 0",
                (int(time.time()),),
            ).fetchall()
    except sqlite3.Error as exc:
        print(f"[!] Giveaway database check failed; will retry later: {exc}")
        return

    for giveaway_id, channel_id, message_id in records:
        try:
            channel = guild.get_channel(channel_id)
            if channel is None:
                # A missing or foreign channel must never be read or replied to.
                update_giveaway_record(giveaway_id, guild_id, delete=True)
                continue

            message = await channel.fetch_message(message_id)
            if not message.embeds or not message.embeds[0].description:
                update_giveaway_record(giveaway_id, guild_id, delete=True)
                continue

            embed = message.embeds[0]
            if "Giveaway ended" in embed.description:
                update_giveaway_record(giveaway_id, guild_id)
                continue
            winners = parse_winner_count(embed.description)

            participants = {}
            for reaction in message.reactions:
                if str(reaction.emoji) != "\N{PARTY POPPER}":
                    continue
                async for user in reaction.users():
                    if user.id != client.user.id:
                        participants[user.id] = user
                break

            embed.description = ended_description(embed.description)
            await message.edit(embed=embed)

            if len(participants) < winners:
                await message.reply("Not enough participants for this giveaway.")
                update_giveaway_record(giveaway_id, guild_id)
                continue

            winner_list = random.sample(list(participants.values()), k=winners)
            result_embed = discord.Embed(
                title=embed.title,
                colour=discord.Colour.green(),
            )
            for index, winner_mentions in enumerate(
                chunk_display_values([winner.mention for winner in winner_list])
            ):
                field_name = "Winners" if index == 0 else "Winners (continued)"
                result_embed.add_field(
                    name=field_name, value=winner_mentions, inline=False
                )
            result_embed.set_footer(text="Giveaway ended")
            await message.reply(embed=result_embed)
            update_giveaway_record(giveaway_id, guild_id)
        except discord.NotFound:
            update_giveaway_record(giveaway_id, guild_id, delete=True)
        except (
            discord.Forbidden,
            discord.HTTPException,
            sqlite3.Error,
            ValueError,
        ) as exc:
            print(f"[!] Could not finalize giveaway {giveaway_id}; will retry: {exc}")
        except Exception as exc:
            print(f"[!] Unexpected giveaway error for {giveaway_id}; will retry: {exc}")


def fetch_twitch_streams(guild_configs):
    """Return configured live streams using bounded blocking HTTP calls."""
    with requests.Session() as session:
        configured_channels = []
        for guild_id, guild_config in guild_configs:
            if guild_config.get("twitchChannelName") and guild_config.get("twChannelId"):
                configured_channels.append((
                    guild_id, guild_config["twChannelId"], guild_config["twitchChannelName"], True,
                ))
            configured_channels.extend(
                (guild_id, item.get("friendChannelId"), item.get("friendChannel"), False)
                for item in guild_config.get("friendTwitch", [])
                if item.get("friendChannelId") and item.get("friendChannel")
            )

        for authentication_attempt in range(2):
            access_token = twitch_token_cache.get_access_token(
                session,
                client_id=clientid,
                client_secret=clientsecret,
                timeout=15,
            )
            headers = {
                "Client-ID": clientid,
                "Authorization": f"Bearer {access_token}",
            }
            retry_authentication = False
            live_streams = []
            for guild_id, discord_channel_id, twitch_name, is_primary in configured_channels:
                response = session.get(
                    "https://api.twitch.tv/helix/streams",
                    params={"user_login": twitch_name},
                    headers=headers,
                    timeout=15,
                )
                if response.status_code == 401:
                    twitch_token_cache.invalidate()
                    if authentication_attempt == 0:
                        retry_authentication = True
                        break
                response.raise_for_status()
                streams = response.json().get("data", [])
                if streams:
                    live_streams.append(
                        (guild_id, discord_channel_id, twitch_name, is_primary, streams[0])
                    )
            if retry_authentication:
                continue
            return live_streams
    return []


@tasks.loop(seconds=60)
async def twitchloop():
    try:
        settings = [(guild.id, guild_config) for guild, guild_config in active_guild_configs(client.guilds)]
        streams = await asyncio.to_thread(fetch_twitch_streams, settings)
    except Exception as exc:
        print(f"[!] Twitch notification check failed: {exc}")
        return

    for guild_id, discord_channel_id, twitch_name, is_primary, stream_data in streams:
        guild = client.get_guild(guild_id)
        if guild is None:
            continue
        channel = guild.get_channel(discord_channel_id)
        if channel is None:
            print(
                f"[!] Twitch notification channel {discord_channel_id} is unavailable."
            )
            continue

        stream_id = stream_data.get("id")
        key = (guild_id, stream_id)
        if not stream_id or key in notified:
            continue
        game_name = stream_data.get("game_name")
        if is_primary:
            guild_config = load_active_guild_config(guild_id)
            ping_role_id = int(
                guild_config.get("managedResources", {}).get("selfRoles", {})
                .get("pings", {}).get("Now Streaming Pings", 0) or 0
            )
            role_ping = f"<@&{ping_role_id}> " if ping_role_id and guild.get_role(ping_role_id) else ""
            message = f"**{role_ping}I'm live!**\nhttps://www.twitch.tv/{twitch_name}"
        else:
            ping_role_id = 0
            message = (
                f"**Server friend '{twitch_name}' is live!**\n"
                f"https://www.twitch.tv/{twitch_name}"
            )
        if game_name:
            message += f"\nPlaying: {game_name}"
        try:
            allowed_roles = (
                [discord.Object(id=ping_role_id)] if is_primary and role_ping else []
            )
            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=allowed_roles,
                    replied_user=False,
                ),
            )
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            print(
                f"[!] Twitch notification send failed for {twitch_name}; "
                f"will retry: {exc}"
            )
            continue
        notified.add(key)
        notified_order.append(key)
        try:
            await asyncio.to_thread(
                remember_notified_stream,
                giveaway_path(guild_id),
                stream_id,
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            print(f"[!] Could not persist Twitch stream {stream_id}: {exc}")
        while len(notified_order) > 5000:
            notified.discard(notified_order.popleft())


@tasks.loop(minutes=5)
async def youtubeloop():
    for guild, guild_config in active_guild_configs(client.guilds):
        source = guild_config.get("ytChannel")
        channel_id = int(guild_config.get("ytChannelId", 0) or 0)
        if not source or not channel_id:
            continue
        channel = guild.get_channel(channel_id)
        if channel is None:
            print(f"[!] YouTube notification channel {channel_id} is unavailable in {guild.id}.")
            continue
        try:
            fetched_content = await asyncio.to_thread(fetch_youtube_content, 3, source)
            mark_youtube_success()
            seen = previous.setdefault(guild.id, set())
            if guild.id not in youtube_cache_primed:
                for results in fetched_content:
                    for result in results:
                        video_id = result.get("videoId")
                        if video_id:
                            seen.add(video_id)
                youtube_cache_primed.add(guild.id)
                print(f"[OK] YouTube notifications initialized in {guild.id} with {len(seen)} recent item(s).")
                continue
            for results in fetched_content:
                for result in results:
                    video_id = result.get("videoId")
                    if video_id and video_id not in seen:
                        await channel.send(
                            "**New YouTube upload**\n"
                            f"https://www.youtube.com/watch?v={video_id}",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        seen.add(video_id)
        except Exception as exc:
            report_youtube_failure(f"notification check in {guild.id}", exc)


@client.event
async def on_guild_join(guild: discord.Guild):
    try:
        guild_config = load_active_guild_config(guild.id)
    except ConfigError:
        print(f"[!] Ignoring unconfigured guild {guild.id}.")
        return
    await client.tree.sync(guild=guild)
    restore_role_buttons_for_guild(guild)
    await restore_twitch_state_for_guild(guild)
    await reconcile_managed_guild(guild, guild_config)
    if guild_config.get("kickMemberFunction") and guild_config.get("verified") and not check_members_task.is_running():
        check_members_task.start()
    if guild_config.get("ytChannel") and guild_config.get("ytChannelId") and not youtubeloop.is_running():
        youtubeloop.start()
    if clientid and clientsecret and (
        (guild_config.get("twitchChannelName") and guild_config.get("twChannelId"))
        or guild_config.get("friendTwitch")
    ) and not twitchloop.is_running():
        twitchloop.start()
    ticket_cog = client.get_cog("OnInteractionEvent")
    if ticket_cog is not None:
        await ticket_cog._secure_ticket_guild(guild, guild_config)


@client.event
async def on_member_join(member: discord.Member):
    try:
        guild_config = load_active_guild_config(member.guild.id)
    except ConfigError:
        return
    welcome_channel_id = int(
        guild_config.get("managedResources", {}).get("welcomeMessagesChannel")
        or guild_config["welcome"]
    )
    welcome = member.guild.get_channel(welcome_channel_id)
    if welcome is None:
        print(f"[!] Welcome channel {welcome_channel_id} is unavailable in {member.guild.id}.")
        return
    embed = discord.Embed(
        title=f"👋 Welcome to {member.guild.name}!",
        description=f"Hello {member.mention}. We are glad you are here.",
        colour=client.colour,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(
        name="Getting started",
        value=(
            "Please read this server's rules and use its ticket panel if you need help.\n"
            "Use the self-role and verification panels to personalize your profile.\n"
        ),
        inline=False,
    )

    welcome_file = None
    try:
        background = Editor("Data/welcome.jpg")
        profile_image = await load_image_async(str(member.display_avatar.url))
        profile = Editor(profile_image).resize((250, 250)).circle_image()
        poppins = Font.poppins(size=75, variant="bold")
        poppins_small = Font.poppins(size=50, variant="light")
        background.paste(profile, (390, 50))
        background.ellipse((390, 50), 250, 250, outline="black", stroke_width=4)
        background.text(
            (525, 300), "WELCOME !", color="white", font=poppins, align="center"
        )
        background.text(
            (525, 360), member.name, color="white", font=poppins_small, align="center"
        )

        welcome_file = discord.File(fp=background.image_bytes, filename="wlcbg.jpg")
        embed.set_image(url="attachment://wlcbg.jpg")
    except Exception as exc:
        print(f"[!] Welcome image generation failed; sending text embed instead: {exc}")

    try:
        send_options = {"embed": embed}
        if welcome_file is not None:
            send_options["file"] = welcome_file
        await welcome.send(**send_options)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        print(f"[!] Could not send welcome message for member {member.id}: {exc}")
    finally:
        if welcome_file is not None:
            welcome_file.close()


def initialize_databases():
    """Create all runtime tables and safely migrate the warnings schema."""
    (BASE_DIR / "Data").mkdir(exist_ok=True)
    (BASE_DIR / "Transcripts").mkdir(exist_ok=True)

    with sqlite3.connect(BASE_DIR / "Data" / "users.db") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "userid INTEGER PRIMARY KEY, balance INTEGER, invited INTEGER, "
            "left INTEGER, voice INTEGER DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS giveaways ("
            "id INTEGER, ends INTEGER, channel INTEGER, message INTEGER, ended INTEGER)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS warnings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, userid INTEGER NOT NULL, "
            "reason TEXT, warner INTEGER)"
        )

        warning_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(warnings)").fetchall()
        }
        if "id" not in warning_columns:
            legacy_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='warnings_legacy'"
            ).fetchone()
            if not legacy_exists:
                conn.execute("ALTER TABLE warnings RENAME TO warnings_legacy")
                conn.execute(
                    "CREATE TABLE warnings ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, userid INTEGER NOT NULL, "
                    "reason TEXT, warner INTEGER)"
                )
                conn.execute(
                    "INSERT INTO warnings (userid, reason, warner) "
                    "SELECT userid, reason, warner FROM warnings_legacy"
                )
                print("[!] Migrated warnings database; preserved warnings_legacy.")
        warning_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(warnings)").fetchall()
        }
        if "created_at" not in warning_columns:
            conn.execute("ALTER TABLE warnings ADD COLUMN created_at INTEGER")
        if "expires_at" not in warning_columns:
            conn.execute("ALTER TABLE warnings ADD COLUMN expires_at INTEGER")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS warnings_userid_idx ON warnings(userid)"
        )

    with sqlite3.connect(BASE_DIR / "Data" / "user.db") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS roles ("
            "channelid INTEGER, messageid INTEGER, roleid INTEGER, "
            "emoji TEXT, content TEXT, custom_id TEXT)"
        )
        role_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(roles)").fetchall()
        }
        if "custom_id" not in role_columns:
            conn.execute("ALTER TABLE roles ADD COLUMN custom_id TEXT")

        reserved_component_ids = (
            "verify",
            "roles",
            "modmail_del",
            "transcript",
            "close",
            "delete",
            "reopen",
            "ticket_help",
            "ticket_suggestions",
            "ticket_report",
            "voicechannel",
        )
        placeholders = ", ".join("?" for _ in reserved_component_ids)
        conn.execute(
            f"UPDATE roles SET custom_id = CASE "
            f"WHEN content IN ({placeholders}) THEN 'role_button:' || roleid "
            "ELSE content END "
            "WHERE custom_id IS NULL OR custom_id = ''",
            reserved_component_ids,
        )

    with sqlite3.connect(BASE_DIR / "sticky.db") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS infos_salos ("
            "id_salon INTEGER PRIMARY KEY, contenu TEXT, message_limit INTEGER)"
        )


async def handle_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
):
    """Give every failed slash command a safe response and retain diagnostics."""
    original = getattr(error, "original", error)
    print(
        f"[!] Application command error ({type(original).__name__}): {original}",
        file=sys.stderr,
    )
    message = app_command_error_message(error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        print(f"[!] Could not deliver application-command error response: {exc}")


client.tree.on_error = handle_app_command_error


@client.event
async def setup_hook():
    initialize_databases()
    try:
        synced_commands = await client.tree.sync()
        print(f"[!] Synced {len(synced_commands)} commands")
    except Exception as exc:
        print(f"[!] Command sync failed and will be retried on the next start: {exc}")
    print("[!] Runtime databases ready")


async def loadcogs():
    for filename in sorted(os.listdir("Commands")):
        if filename.endswith(".py") and not filename.startswith("_"):
            await client.load_extension(f"Commands.{filename[:-3]}")


def configure_client_state():
    client.sticky = {}
    client.persistent_state_loaded = False
    client.restored_role_guilds = set()
    client.twitch_state_loaded = set()
    client.panels_reconciled = set()
    client.headers_reconciled = set()
    client.layout_reconciled = set()
    client.dashboard_attempted = False
    client.dashboard_server = None
    client.configured_guild_id = guildId
    client.colour = discord.Colour.from_rgb(101, 255, 0)
    client.modmailid = modmailid


async def check_installation():
    initialize_databases()
    configure_client_state()
    configured_role_ids = load_role_ids()
    print(f"[OK] Validated {len(configured_role_ids)} reaction-role menu IDs")
    async with client:
        await loadcogs()
        loaded = sorted(client.extensions)
        print(f"[OK] Loaded {len(loaded)} extensions: {', '.join(loaded)}")

        with sqlite3.connect("Data/user.db") as conn:
            saved_role_buttons = conn.execute(
                "SELECT roleid, emoji, content, custom_id FROM roles"
            ).fetchall()
        for role_id, emoji, content, custom_id in saved_role_buttons:
            view = mAddBtn(
                content=content,
                emoji=emoji,
                role=discord.Object(id=role_id),
                custom_id=custom_id,
            )
            if len(view.children) != 1:
                raise RuntimeError(
                    f"Saved role button for role {role_id} could not be restored."
                )
        print(f"[OK] Validated {len(saved_role_buttons)} saved role buttons")

        for extension in reversed(loaded):
            await client.unload_extension(extension)

    warnings = configuration_warnings(config)
    if warnings:
        print("[i] Optional configuration: " + "; ".join(warnings) + ".")
    missing = missing_required_settings(config)
    if missing:
        print("[i] Add these settings before connecting: " + ", ".join(missing) + ".")
    print("[OK] Project L installation check passed.")


async def startup():
    configure_client_state()
    async with client:
        await loadcogs()
        try:
            await client.start(token)
        finally:
            if client.dashboard_server is not None:
                await client.dashboard_server.stop()


def main():
    if "--check" in sys.argv[1:]:
        asyncio.run(check_installation())
        return 0

    missing = missing_required_settings(config)
    if missing:
        print("[!] Configuration is incomplete:", file=sys.stderr)
        for setting in missing:
            print(f"    - {setting}", file=sys.stderr)
        print(
            "Copy values into Data/config.json, or set DISCORD_BOT_TOKEN, then run again.",
            file=sys.stderr,
        )
        return 2

    for warning in configuration_warnings(config):
        print(f"[i] {warning}.")

    try:
        asyncio.run(startup())
    except discord.PrivilegedIntentsRequired:
        print(
            "[!] Enable Server Members, Presence, and Message Content intents in "
            "the Discord Developer Portal.",
            file=sys.stderr,
        )
        return 3
    except discord.LoginFailure:
        print("[!] Discord rejected the configured bot token.", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("\n[!] Bot stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
