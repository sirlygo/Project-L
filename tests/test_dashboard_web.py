import unittest
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from dashboard_web import Dashboard, dashboard_options, sign_session, verify_session


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


class DashboardOptionTests(unittest.TestCase):
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
