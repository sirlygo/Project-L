"""Background jobs must never act on a different server's resources."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot import check_guild_giveaways


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

