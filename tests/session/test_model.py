import unittest
from unittest.mock import AsyncMock, patch

from web_llm_bridge.session.model import WebLLMSession
from web_llm_bridge.client import WebLLMClient


class SessionModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_id_and_reopen_setting_are_sent_to_broker(self) -> None:
        response = {"provider": "chatgpt", "session_id": "saved", "conversation_url": "https://chatgpt.com/c/a", "reopen_on_closed": True}
        with patch("web_llm_bridge.session.model.rpc_call", AsyncMock(return_value=response)) as rpc:
            session = await WebLLMSession.open(session_id="saved", reopen_on_closed=True)
        self.assertEqual(session.session_id, "saved")
        self.assertTrue(rpc.await_args.kwargs == {} or rpc.await_args.args[1]["session_id"] == "saved")
        self.assertTrue(rpc.await_args.args[1]["reopen_on_closed"])

    async def test_history_public_default_is_none(self) -> None:
        session = WebLLMSession(session_id="saved")
        with patch("web_llm_bridge.session.model.rpc_call", AsyncMock(return_value={"messages": []})) as rpc:
            await session.get_messages()
        self.assertIsNone(rpc.await_args.args[1]["limit"])

    async def test_restoring_session_preserves_reopen_policy_by_default(self) -> None:
        response = {
            "provider": "chatgpt",
            "session_id": "saved",
            "conversation_url": "https://chatgpt.com/c/a",
            "reopen_on_closed": True,
        }
        with patch(
            "web_llm_bridge.session.model.rpc_call",
            AsyncMock(return_value=response),
        ) as rpc:
            session = await WebLLMSession.open(session_id="saved")
        self.assertTrue(session.reopen_on_closed)
        self.assertIsNone(rpc.await_args.args[1]["reopen_on_closed"])

    async def test_client_open_preserves_reopen_policy_by_default(self) -> None:
        client = WebLLMClient()
        with patch.object(
            client,
            "call",
            AsyncMock(return_value={"session_id": "saved"}),
        ) as call:
            await client.open(session_id="saved")
        self.assertIsNone(call.await_args.args[1]["reopen_on_closed"])
