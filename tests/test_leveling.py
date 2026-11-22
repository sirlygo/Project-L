import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from Commands.leveling import add_xp, level_for_xp, member_xp


class LevelingTests(unittest.TestCase):
    def test_chat_cooldown_voice_independence_and_milestones(self):
        with TemporaryDirectory() as directory, patch(
            "Commands.leveling.DB_PATH", Path(directory) / "levels.db"
        ):
            self.assertEqual(add_xp(1, 2, "chat", 20, now=100), None)
            self.assertEqual(add_xp(1, 2, "chat", 20, now=120), None)
            self.assertEqual(member_xp(1, 2), (20, 0))
            self.assertEqual(add_xp(1, 2, "voice", 2500, now=120), 5)
            self.assertEqual(member_xp(1, 2), (20, 2500))
            self.assertEqual(add_xp(1, 2, "chat", 2480, now=161), 5)
            self.assertEqual(member_xp(1, 2), (2500, 2500))

    def test_level_thresholds(self):
        self.assertEqual([level_for_xp(value) for value in (0, 99, 100, 2499, 2500)], [0, 0, 1, 4, 5])
