"""Background jobs must never act on a different server's resources."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot import check_guild_giveaways, reconcile_managed_guild


class GiveawayIsolationTests(unittest.IsolatedAsyncioTestCase):
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

