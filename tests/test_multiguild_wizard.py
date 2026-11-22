"""Additional-server setup never carries primary server resource IDs across."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from configure_gui import ProjectLSetupWizard


class AdditionalServerSetupTests(unittest.TestCase):
    def test_new_server_starts_from_template_not_primary_resource_ids(self):
        with TemporaryDirectory() as directory:
            wizard = ProjectLSetupWizard.__new__(ProjectLSetupWizard)
            wizard.target_guild_id = 2
            wizard.config_path = Path(directory) / "2" / "config.json"
            wizard.roles_path = wizard.config_path.with_name("roles.json")
            wizard.primary_config = {
                "guildId": 1, "client_id": 10, "token": "private",
                "twClientId": "shared", "twClientsecret": "secret",
                "welcome": 999, "verified": 888,
            }
            wizard.startup_warnings = []
            config = wizard._load_config_for_editing()
            self.assertEqual(config["guildId"], 2)
            self.assertEqual(config["client_id"], 10)
            self.assertEqual(config["token"], "private")
            self.assertNotEqual(config["welcome"], 999)
            self.assertNotEqual(config["verified"], 888)
            self.assertEqual(wizard._load_roles_for_editing(), [])

