import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from Commands.public_voice import (
    clean_room_name, forget_room, old_empty_rooms,
    remember_room, room_for_owner, tracked_room,
)


class PublicVoiceTests(unittest.TestCase):
    def test_names_are_trimmed_and_empty_names_rejected(self):
        self.assertEqual(clean_room_name("  My   Game  "), "My Game")
        with self.assertRaises(ValueError):
            clean_room_name(" \n ")

    def test_room_tracking_is_persistent_and_scoped(self):
        with TemporaryDirectory() as directory, patch(
            "Commands.public_voice.DB_PATH", Path(directory) / "users.db"
        ):
            remember_room(33, 11, 22)
            self.assertEqual(room_for_owner(11, 22), (33,))
            self.assertEqual(room_for_owner(12, 22), None)
            self.assertEqual(tracked_room(33)[:2], (11, 22))
            self.assertEqual(old_empty_rooms(2**63 - 1), [(33, 11)])
            forget_room(33)
            self.assertIsNone(tracked_room(33))
