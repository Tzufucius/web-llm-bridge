import tempfile
import unittest

from web_llm_bridge.artifacts.model import make_artifact_id
from web_llm_bridge.artifacts.store import ArtifactStore
from web_llm_bridge.providers.base import ProviderDefinition
from web_llm_bridge.errors import RPCError, WebLLMBridgeError
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
        self.started = False

    async def start(self):
        if not self.started:
            self.starts += 1
            self.started = True

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

    async def test_chat_transport_loss_is_not_replayable(self):
        class LosingTransport(FakeTransport):
            async def request(self, method, params, **kwargs):
                raise RPCError("断连", "EXTENSION_NOT_CONNECTED")

        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(SessionStore(sessions_dir=directory), FakeRegistry(), LosingTransport())
            with self.assertRaises(WebLLMBridgeError) as caught:
                await manager._request_browser("chat", {"provider": "first", "tab_id": 1, "text": "hello"}, timeout_ms=1000)
        self.assertEqual(caught.exception.code, "CHAT_STATE_UNKNOWN")

    async def test_get_artifact_binds_closed_session_and_cleans_temporary_tab(self):
        class ArtifactTransport(FakeTransport):
            def __init__(self):
                super().__init__()
                self.next_tab = 10

            async def request(self, method, params, **kwargs):
                self.calls.append((method, params))
                if method == "open":
                    self.next_tab += 1
                    return {"tab_id": self.next_tab, "url": params["url"]}
                if method == "get_artifact":
                    return {"tab_id": params["tab_id"], "url": "https://first.example/c/one", "_artifact_bytes": b"\x89PNG\r\n\x1a\nsynthetic", "_artifact_mime_type": "image/png", "_source": "blob:https://first.example/refreshed", "_source_kind": "blob"}
                if method == "close_tab":
                    return {"tab_id": params["tab_id"], "closed": True}
                raise AssertionError(method)

        with tempfile.TemporaryDirectory() as directory:
            transport = ArtifactTransport()
            artifacts = ArtifactStore(f"{directory}/artifacts")
            manager = SessionManager(SessionStore(sessions_dir=directory), FakeRegistry(), transport, artifacts)
            opened = await manager.open(provider="first", url="https://first.example/c/one")
            artifact_id = make_artifact_id("first", "turn-1", 0)
            artifacts.upsert(session_id=opened["session_id"], provider="first", conversation_url=opened["conversation_url"], descriptor={"id": artifact_id, "kind": "image", "provider": "first", "turn_id": "turn-1", "index": 0, "mime_type": "image/png"}, source_kind="blob", source="blob:https://first.example/stale")
            await manager.close_session(provider="first", session_id=opened["session_id"])
            with tempfile.TemporaryDirectory() as output_dir:
                materialized = await manager.get_artifact(artifact_id, output=f"{output_dir}/image.png")
            saved = manager.store.get(opened["session_id"], "first")

        self.assertEqual(materialized["id"], artifact_id)
        self.assertEqual(materialized["mime_type"], "image/png")
        self.assertFalse(saved["active"])
        self.assertEqual([method for method, _ in transport.calls].count("close_tab"), 2)
        self.assertIn("get_artifact", [method for method, _ in transport.calls])
