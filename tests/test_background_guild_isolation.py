"""Background jobs must never act on a different server's resources."""

import sqlite3
import tempfile
import unittest
from collections import deque
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot import (
    check_guild_giveaways, member_cleanup_date_path, read_last_date,
    reconcile_managed_guild, twitchloop, write_last_date,
)
from Commands.panels import ensure_automatic_panels


class GiveawayIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_cleanup_watermark_is_per_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("bot.guildId", 1), \
                 patch("bot.guild_config_path", side_effect=lambda guild_id: root / str(guild_id) / "config.json"):
                path_one = member_cleanup_date_path(1)
                path_two = member_cleanup_date_path(2)
            self.assertNotEqual(path_one, path_two)
            moment = read_last_date(path_two)
            write_last_date(moment, path_two)
            self.assertEqual(read_last_date(path_two), moment)
            self.assertTrue(path_two.is_file())

    async def test_panel_installation_rejects_foreign_channel_id(self):
        guild = SimpleNamespace(id=1, get_channel=lambda _id: SimpleNamespace(guild=SimpleNamespace(id=2)))
        client = SimpleNamespace(get_guild=lambda _id: guild, get_channel=lambda _id: None)
        config = {"guildId": 1, "welcome": 20, "managedResources": {"panelsChannel": 10}}
        report = await ensure_automatic_panels(client, config)
        self.assertIn("panels channel belongs to another server", report.failed)

    async def test_foreign_channel_record_is_not_fetched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "giveaways.db"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "CREATE TABLE giveaways (id INTEGER, ends INTEGER, "
                    "channel INTEGER, message INTEGER, ended INTEGER)"
                )
                db.execute("INSERT INTO giveaways VALUES (1, 0, 999, 10, 0)")
            guild = SimpleNamespace(id=2, get_channel=lambda channel_id: None)
            with patch("bot.giveaway_path", return_value=path):
                await check_guild_giveaways(guild)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM giveaways").fetchone()[0], 0)

    async def test_panel_reconciliation_uses_each_guild_configuration(self):
        fake_client = SimpleNamespace(
            panels_reconciled=set(), headers_reconciled=set(), layout_reconciled=set(),
        )
        guild_one = SimpleNamespace(id=1, get_channel=lambda _id: None)
        guild_two = SimpleNamespace(id=2, get_channel=lambda _id: None)
        config_one = {"guildId": 1, "managedResources": {}, "tickets": {}}
        config_two = {"guildId": 2, "managedResources": {}, "tickets": {}}
        report = SimpleNamespace(created=[], updated=[], moved=[], failed=[])
        with patch("bot.client", fake_client), \
             patch("bot.ensure_automatic_panels", new_callable=AsyncMock, return_value=report) as panels, \
             patch("bot.ensure_channel_headers", new_callable=AsyncMock, return_value=[]) as headers:
            await reconcile_managed_guild(guild_one, config_one)
            await reconcile_managed_guild(guild_two, config_two)
        self.assertEqual([call.args[1] for call in panels.await_args_list], [config_one, config_two])
        self.assertEqual([call.args[1] for call in headers.await_args_list], [config_one, config_two])
        self.assertEqual(fake_client.panels_reconciled, {1, 2})

    async def test_same_twitch_stream_notifies_each_server_once(self):
        sent_one = AsyncMock()
        sent_two = AsyncMock()
        configs = {
            1: {"guildId": 1, "managedResources": {}},
            2: {"guildId": 2, "managedResources": {}},
        }
        guilds = {
            1: SimpleNamespace(id=1, get_channel=lambda _id: SimpleNamespace(send=sent_one), get_role=lambda _id: None),
            2: SimpleNamespace(id=2, get_channel=lambda _id: SimpleNamespace(send=sent_two), get_role=lambda _id: None),
        }
        client = SimpleNamespace(guilds=list(guilds.values()), get_guild=lambda guild_id: guilds[guild_id])
        streams = [
            (1, 100, "creator", True, {"id": "same-stream"}),
            (2, 200, "creator", True, {"id": "same-stream"}),
        ]
        with patch("bot.client", client), \
             patch("bot.active_guild_configs", return_value=iter((guilds[i], configs[i]) for i in (1, 2))), \
             patch("bot.fetch_twitch_streams", return_value=streams), \
             patch("bot.load_active_guild_config", side_effect=lambda guild_id: configs[guild_id]), \
             patch("bot.remember_notified_stream"), \
             patch("bot.giveaway_path", return_value=Path("unused.db")), \
             patch("bot.notified", set()), patch("bot.notified_order", deque()):
            await twitchloop.coro()
        sent_one.assert_awaited_once()
        sent_two.assert_awaited_once()

