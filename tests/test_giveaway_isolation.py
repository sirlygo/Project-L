import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from Commands.giveaways import giveaway_path


class GiveawayIsolationTests(unittest.TestCase):
    def test_secondary_guilds_get_separate_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("Commands.giveaways.load_config", return_value={"guildId": 1}), patch(
                "Commands.giveaways.guild_database_path",
                side_effect=lambda guild_id, _database, primary_guild_id: root / str(guild_id) / "users.db",
            ):
                second = giveaway_path(2)
                third = giveaway_path(3)
            with closing(sqlite3.connect(second)) as db, db:
                db.execute("INSERT INTO giveaways VALUES(5,100,10,20,0)")
            with closing(sqlite3.connect(third)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM giveaways").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
