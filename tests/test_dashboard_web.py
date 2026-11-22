import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from dashboard_web import Dashboard, dashboard_options, sign_session, verify_session
from config_loader import ConfigError


class DashboardSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        options = {
            "url": "http://localhost:8765", "client_id": 123,
            "client_secret": "example", "session_secret": b"s" * 32, "port": 8765,
        }
        bot = SimpleNamespace(get_guild=lambda _guild_id: None)
        self.client = TestClient(TestServer(Dashboard(bot, options).app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_unauthenticated_staff_data_and_mutations_are_rejected(self):
        response = await self.client.get("/api/overview")
        self.assertEqual(response.status, 401)
        response = await self.client.put("/api/settings", json={})
        self.assertEqual(response.status, 403)

    async def test_session_info_does_not_leak_data(self):
        response = await self.client.get("/api/session")
        self.assertEqual(await response.json(), {"authenticated": False})


class MultiGuildDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_request_authorizes_the_selected_server(self):
        secret = b"s" * 32
        options = {
            "url": "http://localhost:8765", "client_id": 123,
            "client_secret": "example", "session_secret": secret, "port": 8765,
        }
        allowed = SimpleNamespace(
            id=777, guild_permissions=SimpleNamespace(
                administrator=True, manage_guild=True, manage_messages=True,
                manage_channels=True, moderate_members=True,
            ),
        )
        async def no_member(_user_id):
            return None
        guilds = {
            1: SimpleNamespace(id=1, name="One", owner_id=777, get_member=lambda _id: allowed),
            2: SimpleNamespace(id=2, name="Two", owner_id=888, get_member=lambda _id: None,
                               fetch_member=no_member),
        }
        bot = SimpleNamespace(guilds=list(guilds.values()), get_guild=lambda guild_id: guilds.get(guild_id))
        client = TestClient(TestServer(Dashboard(bot, options).app))
        await client.start_server()
        primary = {"guildId": 1}

        def active_config(guild_id):
            if guild_id not in guilds:
                raise ConfigError("Unknown server")
            return {"guildId": guild_id}

        try:
            with patch("dashboard_web.load_config", return_value=primary), \
                 patch("dashboard_web.load_active_guild_config", side_effect=active_config), \
                 patch("dashboard_web.active_guild_configs", return_value=iter((guild, {"guildId": guild.id}) for guild in guilds.values())):
                cookies = {"pl_session": sign_session(777, secret)}
                selected = await client.get("/api/session?guild_id=1", cookies=cookies)
                data = await selected.json()
                self.assertTrue(data["owner"])
                self.assertEqual(data["guildId"], "1")
                other = await client.get("/api/session?guild_id=2", cookies=cookies)
                self.assertFalse((await other.json())["staff"])
                denied = await client.get("/api/settings?guild_id=2", cookies=cookies)
                self.assertEqual(denied.status, 403)
                unknown = await client.get("/api/settings?guild_id=3", cookies=cookies)
                self.assertEqual(unknown.status, 403)
        finally:
            await client.close()


class DashboardOptionTests(unittest.TestCase):
    def test_secondary_settings_file_does_not_copy_bot_credentials(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "2" / "config.json"
            path.parent.mkdir()
            Dashboard._write_guild_config(
                {"guildId": 2, "token": "private", "twClientId": "shared",
                 "twClientsecret": "secret", "branding": {"rulesText": "Rules"}},
                path,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["branding"]["rulesText"], "Rules")
            self.assertEqual(saved["token"], "")
            self.assertEqual(saved["twClientsecret"], "")

    def test_signatures_expire_and_reject_tampering(self):
        secret = b"s" * 32
        token = sign_session(123, secret, now=100)
        self.assertEqual(verify_session(token, secret, now=101), 123)
        self.assertIsNone(verify_session(token, secret, now=50000))
        self.assertIsNone(verify_session(token + "x", secret, now=101))
        self.assertIsNone(verify_session("bad.data", secret, now=101))

    def test_dashboard_requires_secret_and_https(self):
        config = {"client_id": 123}
        self.assertIsNone(dashboard_options(config, {}))
        with self.assertRaises(ValueError):
            dashboard_options(config, {
                "PROJECTL_DASHBOARD_PUBLIC_URL": "http://example.org",
                "DISCORD_CLIENT_SECRET": "secret",
                "PROJECTL_DASHBOARD_SESSION_SECRET": "s" * 32,
            })
