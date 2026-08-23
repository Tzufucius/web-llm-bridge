import unittest
from unittest.mock import AsyncMock, patch

from web_llm_bridge.session.model import WebLLMSession
from web_llm_bridge.client import WebLLMClient


class SessionModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_id_is_sent_to_broker_without_legacy_policy(self) -> None:
        response = {"provider": "chatgpt", "session_id": "saved", "conversation_url": "https://chatgpt.com/c/a"}
        with patch("web_llm_bridge.session.model.rpc_call", AsyncMock(return_value=response)) as rpc:
            session = await WebLLMSession.open(session_id="saved")
        self.assertEqual(session.session_id, "saved")
        self.assertEqual(rpc.await_args.args[1], {"provider": "chatgpt", "new": False, "url": None, "session_id": "saved"})

    async def test_history_public_default_is_none(self) -> None:
        session = WebLLMSession(session_id="saved")
        with patch("web_llm_bridge.session.model.rpc_call", AsyncMock(return_value={"messages": []})) as rpc:
            await session.get_messages()
        self.assertIsNone(rpc.await_args.args[1]["limit"])

    async def test_client_open_does_not_send_legacy_policy(self) -> None:
        client = WebLLMClient()
        with patch.object(
            client,
            "call",
            AsyncMock(return_value={"session_id": "saved"}),
        ) as call:
            await client.open(session_id="saved")
        self.assertNotIn("reopen_on_closed", call.await_args.args[1])
