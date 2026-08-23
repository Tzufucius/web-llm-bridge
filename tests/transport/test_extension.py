import asyncio
import base64
import json
import unittest

from web_llm_bridge.transport.extension import ExtensionTransport


class ArtifactTransferTests(unittest.TestCase):
    @staticmethod
    def _transfer(**fields):
        async def create():
            return {"expected": None, "mime_type": None, "next_sequence": 0, "data": bytearray(), "error": None, "done": asyncio.Event(), **fields}
        return asyncio.run(create())

    def test_chunk_sequence_and_size_are_validated(self) -> None:
        transfer = self._transfer()
        ExtensionTransport._handle_artifact_message(transfer, {"type": "artifact_start", "id": "r", "size": 3, "mime_type": "image/png"})
        ExtensionTransport._handle_artifact_message(transfer, {"type": "artifact_chunk", "id": "r", "sequence": 0, "data": base64.b64encode(b"abc").decode()})
        ExtensionTransport._handle_artifact_message(transfer, {"type": "artifact_end", "id": "r"})
        self.assertIsNone(transfer["error"])
        self.assertEqual(bytes(transfer["data"]), b"abc")
        ExtensionTransport._handle_artifact_message(transfer, {"type": "artifact_end", "id": "r"})
        self.assertEqual(transfer["error"].code, "ARTIFACT_TRANSFER_FAILED")

    def test_duplicate_sequence_is_rejected(self) -> None:
        transfer = self._transfer(expected=2, mime_type="image/png", next_sequence=1, data=bytearray(b"a"))
        ExtensionTransport._handle_artifact_message(transfer, {"type": "artifact_chunk", "id": "r", "sequence": 0, "data": base64.b64encode(b"b").decode()})
        self.assertEqual(transfer["error"].code, "ARTIFACT_TRANSFER_FAILED")

    def test_request_keeps_transfer_state_until_chunks_finish(self) -> None:
        async def scenario() -> dict:
            transport = ExtensionTransport()
            transport._client = object()
            transport._ready.set()

            class Client:
                async def send(self, payload: str) -> None:
                    request = json.loads(payload)
                    request_id = request["id"]
                    ExtensionTransport._handle_artifact_message(transport._artifact_transfers[request_id], {"type": "artifact_start", "id": request_id, "size": 3, "mime_type": "image/png"})
                    ExtensionTransport._handle_artifact_message(transport._artifact_transfers[request_id], {"type": "artifact_chunk", "id": request_id, "sequence": 0, "data": base64.b64encode(b"abc").decode()})
                    ExtensionTransport._handle_artifact_message(transport._artifact_transfers[request_id], {"type": "artifact_end", "id": request_id})
                    await transport._handle_message({"type": "response", "id": request_id, "ok": True, "result": {"transferred": True}})

            transport._client = Client()
            return await transport.request("get_artifact", {}, timeout_ms=1000)

        result = asyncio.run(scenario())
        self.assertEqual(result["_artifact_bytes"], b"abc")
        self.assertEqual(result["_artifact_mime_type"], "image/png")
