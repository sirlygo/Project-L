import sqlite3
import unittest

from Commands.private_voice import ensure_private_voice_table, private_room_for_owner


class PrivateVoiceIsolationTests(unittest.TestCase):
    def test_legacy_room_imported_only_for_primary_guild(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE users(userid INTEGER PRIMARY KEY, voice INTEGER)")
            db.execute("INSERT INTO users(userid,voice) VALUES(7,99)")
            ensure_private_voice_table(db, 1)
            self.assertEqual(private_room_for_owner(db, 1, 7)[0], 99)
            self.assertIsNone(private_room_for_owner(db, 2, 7))
            db.execute("INSERT INTO private_voice_rooms VALUES(2,7,123)")
            self.assertEqual(private_room_for_owner(db, 2, 7)[0], 123)


if __name__ == "__main__":
    unittest.main()
