import unittest

from guild_guard import is_configured_guild


class GuildGuardTests(unittest.TestCase):
    def test_only_configured_guild_is_accepted(self):
        config = {"guildId": 123}
        self.assertTrue(is_configured_guild(123, config))
        self.assertFalse(is_configured_guild(456, config))
        self.assertFalse(is_configured_guild(None, config))


if __name__ == "__main__":
    unittest.main()
