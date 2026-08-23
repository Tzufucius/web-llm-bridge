import tempfile
import unittest

from web_llm_bridge.providers.base import ProviderDefinition
from web_llm_bridge.artifacts.store import ArtifactStore
from web_llm_bridge.session.manager import SessionManager
from web_llm_bridge.session.store import SessionStore


class FakeRegistry:
    def get_provider(self, provider):
        return ProviderDefinition(provider, f"https://{provider}.example/", frozenset({f"{provider}.example"}), {})


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.next_tab = 10

    async def start(self):
        return None

    async def close(self):
        return None

    async def request(self, method, params, **kwargs):
        self.calls.append((method, params))
        if method == "open":
            self.next_tab += 1
            return {"tab_id": self.next_tab, "url": params["url"]}
        if method == "chat":
            return {"text": "", "request_id": "transport-request", "artifacts": [{"id": "img_test", "kind": "image", "provider": params["provider"], "turn_id": "turn", "index": 0, "mime_type": "image/png", "quality": "display", "_source": "data:image/png;base64,", "_source_kind": "data"}]}
        if method == "close_tab":
            return {"tab_id": params["tab_id"], "closed": True}
        if method == "get_messages":
            return {"messages": [], "truncated": False, "url": "https://first.example/"}
        raise AssertionError(method)


class SessionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_reopen_forget_and_image_only_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeTransport()
            manager = SessionManager(SessionStore(directory), FakeRegistry(), transport, ArtifactStore(directory + "/artifacts"))
            opened = await manager.open(provider="first", new=True)
            response = await manager.chat("prompt", provider="first", session_id=opened["session_id"])
            self.assertEqual(response["text"], "")
            self.assertEqual(response["request_id"], "transport-request")
            self.assertEqual(len(response["artifacts"]), 1)
            closed = await manager.close_session(provider="first", session_id=opened["session_id"])
            self.assertFalse(closed["active"])
            reopened = await manager.open(provider="first", session_id=opened["session_id"])
            self.assertEqual(reopened["session_id"], opened["session_id"])
            forgotten = await manager.forget_session(provider="first", session_id=opened["session_id"])
            self.assertTrue(forgotten["forgotten"])
            self.assertIsNone(manager.store.get(opened["session_id"]))
            self.assertIsNone(SessionStore(directory).get(opened["session_id"]))
            self.assertIn("close_tab", [method for method, _ in transport.calls])
