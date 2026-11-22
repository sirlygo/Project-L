import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from config_loader import ConfigError
from guild_config import (
    active_guild_configs, guild_config_path, guild_database_path,
    load_active_guild_config, load_guild_config,
)


EXAMPLE = json.loads((Path(__file__).resolve().parents[1] / "Data" / "config.example.json").read_text())


class GuildConfigTests(unittest.TestCase):
    def test_primary_is_unchanged_and_unknown_guild_fails_closed(self):
        primary = {**EXAMPLE, "guildId": 1, "client_id": 10, "token": "private"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIs(load_guild_config(1, root=root, primary_config=primary), primary)
            self.assertIs(load_active_guild_config(1, primary_config=primary), primary)
            with self.assertRaisesRegex(ConfigError, "not enabled"):
                load_active_guild_config(2, primary_config=primary)
            active = list(active_guild_configs([SimpleNamespace(id=1), SimpleNamespace(id=2)],
                                               primary_config=primary))
            self.assertEqual([guild.id for guild, _ in active], [1])
            with self.assertRaises(ConfigError):
                load_guild_config(2, root=root, primary_config=primary)

    def test_server_file_must_match_id_and_app_and_cannot_override_secrets(self):
        primary = {**EXAMPLE, "guildId": 1, "client_id": 10, "token": "private",
                   "twClientId": "shared", "twClientsecret": "shared-secret"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = guild_config_path(2, root=root)
            path.parent.mkdir()
            second = {**EXAMPLE, "guildId": 2, "client_id": 10,
                      "token": "untrusted", "twClientId": "other", "twClientsecret": "other"}
            path.write_text(json.dumps(second), encoding="utf-8")
            loaded = load_guild_config(2, root=root, primary_config=primary)
            self.assertEqual(loaded["token"], "private")
            self.assertEqual(loaded["twClientId"], "shared")
            second["guildId"] = 3
            path.write_text(json.dumps(second), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "does not match"):
                load_guild_config(2, root=root, primary_config=primary)
            second["guildId"] = 2
            second["client_id"] = 11
            path.write_text(json.dumps(second), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "different Discord application"):
                load_guild_config(2, root=root, primary_config=primary)

    def test_invalid_guild_id_cannot_resolve_path(self):
        with self.assertRaises(ConfigError):
            guild_config_path("../other")

    def test_database_paths_are_isolated(self):
        root = Path("C:/project/Data/guilds")
        self.assertEqual(guild_database_path(1, "users.db", root=root, primary_guild_id=1),
                         root.parent / "users.db")
        self.assertEqual(guild_database_path(2, "users.db", root=root, primary_guild_id=1),
                         root / "2" / "users.db")
        with self.assertRaises(ConfigError):
            guild_database_path(2, "../users.db", root=root, primary_guild_id=1)


if __name__ == "__main__":
    unittest.main()
