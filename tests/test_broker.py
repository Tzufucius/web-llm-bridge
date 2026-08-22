import asyncio
import tempfile
import unittest

from tools.chatgpt_web_bridge.chatgpt_broker import PersistentChatGPTBroker
from tools.chatgpt_web_bridge.session_store import SessionStore


class FakeSession:
    opens = 0
    active_chats = 0
    max_active_chats = 0

    def __init__(self, url: str) -> None:
        self._current_url = url
        self._tab_id = FakeSession.opens
        self._progress_callback = None

    @classmethod
    async def open(cls, url: str, reopen_on_closed: bool = True):
        cls.opens += 1
        return cls(url)

    async def get_messages(self, **_kwargs):
        return []

    async def chat(self, text: str):
        FakeSession.active_chats += 1
        FakeSession.max_active_chats = max(FakeSession.max_active_chats, FakeSession.active_chats)
        await asyncio.sleep(0.01)
        FakeSession.active_chats -= 1
        return text

    def _set_progress_callback(self, callback):
        self._progress_callback = callback

    async def _shutdown(self):
        pass


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeSession.opens = 0
        FakeSession.active_chats = 0
        FakeSession.max_active_chats = 0
        self.tempdir = tempfile.TemporaryDirectory()
        self.broker = PersistentChatGPTBroker(
            store=SessionStore(self.tempdir.name),
            session_factory=FakeSession,
        )

    async def asyncTearDown(self) -> None:
        await self.broker.close()
        self.tempdir.cleanup()

    async def test_open_is_idempotent_and_new_preserves_history(self) -> None:
        first = await self.broker.open()
        second = await self.broker.open()
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(FakeSession.opens, 1)

        created = await self.broker.open(new=True)
        self.assertNotEqual(first["session_id"], created["session_id"])
        sessions = await self.broker.list_sessions()
        self.assertEqual(len(sessions), 2)

        restored = await self.broker.open(session_id=first["session_id"])
        self.assertEqual(restored["session_id"], first["session_id"])

    async def test_concurrent_chats_are_serialized(self) -> None:
        await self.broker.open()
        results = await asyncio.gather(
            self.broker.chat("A"),
            self.broker.chat("B"),
        )
        self.assertEqual({item["text"] for item in results}, {"A", "B"})
        self.assertEqual(FakeSession.max_active_chats, 1)

    async def test_protocol_errors_are_stable(self) -> None:
        response = await self.broker.handle_request({"id": "1", "method": "unknown", "params": {}})
        self.assertEqual(response["error"]["code"], "UNKNOWN_METHOD")
        response = await self.broker.handle_request({"method": "open", "params": {}})
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")
        response = await self.broker.handle_request({"id": "2", "method": "list_sessions", "params": {}})
        self.assertTrue(response["ok"])


if __name__ == "__main__":
    unittest.main()
