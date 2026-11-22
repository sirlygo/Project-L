import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from Commands.moderation import warning_path


class WarningIsolationTests(unittest.TestCase):
    def test_secondary_guilds_have_separate_warning_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("Commands.moderation.load_config", return_value={"guildId": 1}), patch(
                "Commands.moderation.guild_database_path",
                side_effect=lambda guild_id, _database, primary_guild_id: root / str(guild_id) / "users.db",
            ):
                second = warning_path(2)
                third = warning_path(3)
            with closing(sqlite3.connect(second)) as db, db:
                db.execute("INSERT INTO warnings(userid,reason,warner) VALUES(7,'test',9)")
            with closing(sqlite3.connect(third)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM warnings").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
