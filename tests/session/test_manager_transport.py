import tempfile
import unittest

from web_llm_bridge.providers.base import ProviderDefinition
from web_llm_bridge.session.manager import SessionManager
from web_llm_bridge.session.store import SessionStore


class FakeRegistry:
    def __init__(self):
        self.providers = {
            "first": ProviderDefinition("first", "https://first.example/", frozenset({"first.example"}), {}),
            "second": ProviderDefinition("second", "https://second.example/", frozenset({"second.example"}), {}),
        }

    def get_provider(self, provider):
        return self.providers[provider]


class FakeTransport:
    def __init__(self):
        self.starts = 0
        self.calls = []

    async def start(self):
        self.starts += 1

    async def close(self):
        return None

    async def request(self, method, params, **kwargs):
        self.calls.append((method, params))
        return {"tab_id": len(self.calls), "url": params["url"]}


class ManagerTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_provider_definitions_share_one_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeTransport()
            manager = SessionManager(SessionStore(sessions_dir=directory), FakeRegistry(), transport)
            await manager.open(provider="first")
            await manager.open(provider="second")
        self.assertEqual(transport.starts, 1)
        self.assertEqual([params["provider"] for _, params in transport.calls], ["first", "second"])
