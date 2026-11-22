import unittest

from Commands.automod import INVITE_LINK


class AutoModTests(unittest.TestCase):
    def test_discord_invites_detected_without_matching_other_domains(self):
        self.assertTrue(INVITE_LINK.search("Join https://discord.gg/example"))
        self.assertTrue(INVITE_LINK.search("https://discord.com/invite/example"))
        self.assertFalse(INVITE_LINK.search("https://discord.gg.example.test/no"))
