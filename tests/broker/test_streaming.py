import asyncio
import json
import unittest

from web_llm_bridge.broker.server import BrokerServer
from web_llm_bridge.protocol import MAX_MESSAGE_BYTES


class FakeManager:
    async def chat(self, text, *, provider, session_id, progress):
        progress({"phase": "submitted"})
        progress({"phase": "streaming"})
        return {"session_id": session_id, "provider": provider, "text": text, "conversation_url": "https://example.invalid/", "sequence": 1}

    async def close(self):
        return None


class LargeResponseManager(FakeManager):
    async def list_sessions(self, provider=None):
        return [{"payload": "x" * MAX_MESSAGE_BYTES}]


class BrokerStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = BrokerServer(FakeManager())
        await self.server.start(port=0)
        self.port = self.server._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.server.close()

    async def test_progress_is_written_before_result(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b'{"id":"a","method":"chat","params":{"text":"hello"}}\n')
        await writer.drain()
        messages = [json.loads((await reader.readline()).decode("utf-8")) for _ in range(3)]
        self.assertEqual([message.get("type") for message in messages[:2]], ["progress", "progress"])
        self.assertTrue(messages[2]["ok"])
        writer.close()
        await writer.wait_closed()

    async def test_eight_mebibyte_boundary_and_overflow_are_structured(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port, limit=MAX_MESSAGE_BYTES + 1)
        writer.write(b" " * MAX_MESSAGE_BYTES + b"\n")
        await writer.drain()
        self.assertEqual(json.loads((await reader.readline()).decode("utf-8"))["error"]["code"], "INVALID_JSON")
        writer.close()
        await writer.wait_closed()

        reader, writer = await asyncio.open_connection("127.0.0.1", self.port, limit=MAX_MESSAGE_BYTES + 1)
        writer.write(b" " * (MAX_MESSAGE_BYTES + 1) + b"\n")
        await writer.drain()
        self.assertEqual(json.loads((await reader.readline()).decode("utf-8"))["error"]["code"], "INVALID_ARGUMENT")
        writer.close()
        await writer.wait_closed()

    async def test_oversized_response_is_replaced_with_structured_error(self):
        await self.server.close()
        self.server = BrokerServer(LargeResponseManager())
        await self.server.start(port=0)
        self.port = self.server._server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", self.port, limit=MAX_MESSAGE_BYTES + 1
        )
        writer.write(b'{"id":"large","method":"list_sessions","params":{}}\n')
        await writer.drain()
        response = json.loads((await reader.readline()).decode("utf-8"))
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "RESPONSE_TOO_LARGE")
        writer.close()
        await writer.wait_closed()
