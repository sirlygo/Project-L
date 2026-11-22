import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from unittest.mock import AsyncMock
from types import SimpleNamespace

from Commands.leveling import Leveling, add_xp, level_for_xp, member_xp


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


class CumulativeMilestoneRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_level_30_keeps_all_lower_lounges(self):
        roles = {5: object(), 15: object(), 30: object()}
        guild = SimpleNamespace(get_role=lambda role_id: roles.get(role_id))
        member = SimpleNamespace(guild=guild, roles=[], add_roles=AsyncMock())
        config = {"managedResources": {"levelRoles": {"chat": {
            "5": 5, "15": 15, "30": 30,
        }}}}
        await Leveling.ensure_milestone_roles(None, member, "chat", 30, config)
        member.add_roles.assert_awaited_once()
        self.assertEqual(member.add_roles.await_args.args, tuple(roles.values()))
