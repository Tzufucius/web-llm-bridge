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

    async def test_chat_transport_loss_is_not_replayable(self):
        class LosingTransport(FakeTransport):
            async def request(self, method, params, **kwargs):
                raise RPCError("断连", "EXTENSION_NOT_CONNECTED")

        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(SessionStore(sessions_dir=directory), FakeRegistry(), LosingTransport())
            with self.assertRaises(WebLLMBridgeError) as caught:
                await manager._request_browser("chat", {"provider": "first", "tab_id": 1, "text": "hello"}, timeout_ms=1000)
        self.assertEqual(caught.exception.code, "CHAT_STATE_UNKNOWN")

    async def test_debug_snapshot_trace_and_wait_artifact(self):
        class DebugTransport(FakeTransport):
            def __init__(self):
                super().__init__()
                self.next_tab = 10

            async def request(self, method, params, **kwargs):
                self.calls.append((method, params))
                if method == "open":
                    self.next_tab += 1
                    return {"tab_id": self.next_tab, "url": params["url"]}
                if method == "debug_snapshot":
                    return {"tab_id": params["tab_id"], "url": "https://first.example/c/one", "snapshot": {"generating": False, "artifacts": []}}
                if method == "debug_trace":
                    return {"tab_id": params["tab_id"], "url": "https://first.example/c/one", "trace": {"request_id": params["request_id"], "events": []}}
                if method == "wait_artifact":
                    return {"tab_id": params["tab_id"], "url": "https://first.example/c/one", "ready": True, "complete": True, "id": params["artifact_id"], "kind": "image", "provider": "first", "turn_id": "turn-1", "index": 0, "mime_type": "image/png", "width": 2, "height": 2, "_source": "data:image/png;base64,AA==", "_source_kind": "data"}
                if method == "close_tab":
                    return {"tab_id": params["tab_id"], "closed": True}
                raise AssertionError(method)

        with tempfile.TemporaryDirectory() as directory:
            transport = DebugTransport()
            artifacts = ArtifactStore(f"{directory}/artifacts")
            manager = SessionManager(SessionStore(sessions_dir=directory), FakeRegistry(), transport, artifacts)
            opened = await manager.open(provider="first", url="https://first.example/c/one")
            snapshot = await manager.debug_snapshot(provider="first", session_id=opened["session_id"])
            trace = await manager.debug_trace(provider="first", session_id=opened["session_id"], request_id="request-1")
            artifact_id = make_artifact_id("first", "turn-1", 0)
            artifacts.upsert(session_id=opened["session_id"], provider="first", conversation_url=opened["conversation_url"], descriptor={"id": artifact_id, "kind": "image", "provider": "first", "turn_id": "turn-1", "index": 0, "mime_type": "image/png"}, source_kind="data", source="data:image/png;base64,AA==")
            await manager.close_session(provider="first", session_id=opened["session_id"])
            waited = await manager.wait_artifact(artifact_id, timeout_ms=1_000)
            saved = manager.store.get(opened["session_id"], "first")

        self.assertFalse(snapshot["snapshot"]["generating"])
        self.assertEqual(trace["trace"]["request_id"], "request-1")
        self.assertTrue(waited["ready"])
        self.assertFalse(saved["active"])
        self.assertEqual([method for method, _ in transport.calls].count("close_tab"), 2)
