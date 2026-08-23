import asyncio
import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_llm_bridge.artifacts.downloader import ArtifactMaterializer
from web_llm_bridge.artifacts.model import ArtifactRecord, make_artifact_id
from web_llm_bridge.artifacts.store import ArtifactStore
from web_llm_bridge.errors import WebLLMBridgeError


PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-png"


def record(source: str, source_kind: str, mime_type: str = "image/png") -> ArtifactRecord:
    return ArtifactRecord(
        id=make_artifact_id("chatgpt", "turn-1", 0),
        kind="image",
        provider="chatgpt",
        session_id="session-1",
        conversation_url="https://chatgpt.com/c/test",
        turn_id="turn-1",
        index=0,
        mime_type=mime_type,
        width=1,
        height=1,
        quality="display",
        source_kind=source_kind,
        source=source,
    )


class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_data_uri_materializes_atomically_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "image.png"
            value = record("data:image/png;base64," + base64.b64encode(PNG).decode(), "data")
            result = await ArtifactMaterializer().materialize(value, target)
            self.assertEqual(Path(result["path"]), target.resolve())
            self.assertEqual(target.read_bytes(), PNG)
            self.assertEqual(result["sha256"], hashlib.sha256(PNG).hexdigest())

    async def test_blob_uses_injected_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = record("blob:https://chatgpt.com/blob", "blob")
            result = await ArtifactMaterializer(blob_fetcher=lambda _: asyncio.sleep(0, result=PNG)).materialize(value, Path(directory) / "image.png")
            self.assertEqual(result["size"], len(PNG))

    async def test_blob_transfer_mime_can_complete_unknown_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = record("blob:https://chatgpt.com/blob", "blob", mime_type="")
            result = await ArtifactMaterializer(blob_fetcher=lambda _: asyncio.sleep(0, result=(PNG, "image/png"))).materialize(value, Path(directory) / "image.png")
            self.assertEqual(result["mime_type"], "image/png")

    async def test_https_download_is_patched_and_validated(self) -> None:
        class Headers:
            def get_content_type(self):
                return "image/png"

        class Response(io.BytesIO):
            headers = Headers()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        with tempfile.TemporaryDirectory() as directory, patch("web_llm_bridge.artifacts.downloader.urlopen", return_value=Response(PNG)):
            value = record("https://cdn.example/image.png", "https")
            result = await ArtifactMaterializer().materialize(value, Path(directory) / "image.png")
            self.assertEqual(result["mime_type"], "image/png")

    async def test_https_authenticated_source_falls_back_to_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("web_llm_bridge.artifacts.downloader.urlopen", side_effect=OSError("403")):
            value = record("https://chatgpt.com/backend-api/estuary/content?id=file", "https")
            result = await ArtifactMaterializer(https_fetcher=lambda _: asyncio.sleep(0, result=(PNG, "image/png"))).materialize(value, Path(directory) / "image.png")
            self.assertEqual(result["mime_type"], "image/png")

    async def test_invalid_magic_bytes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = record("data:image/png;base64," + base64.b64encode(b"not-png").decode(), "data")
            with self.assertRaisesRegex(WebLLMBridgeError, "MIME") as caught:
                await ArtifactMaterializer().materialize(value, Path(directory) / "image.png")
            self.assertEqual(caught.exception.code, "ARTIFACT_INVALID_TYPE")

    def test_store_keeps_private_source_out_of_descriptor_and_deletes_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            value = record("https://cdn.example/signed", "https")
            descriptor = store.upsert(session_id=value.session_id, provider=value.provider, conversation_url=value.conversation_url, descriptor=value.descriptor, source_kind=value.source_kind, source=value.source)
            self.assertNotIn("source", descriptor)
            self.assertEqual(store.get(value.id).source, value.source)
            self.assertEqual(store.delete_session(value.session_id), 1)
            self.assertIsNone(store.get(value.id))

    def test_stable_id_and_created_at_survive_source_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            value = record("https://cdn.example/old", "https")
            first = store.upsert(session_id=value.session_id, provider=value.provider, conversation_url=value.conversation_url, descriptor=value.descriptor, source_kind="https", source=value.source)
            created_at = store.get(value.id).created_at
            second = store.upsert(session_id=value.session_id, provider=value.provider, conversation_url=value.conversation_url, descriptor=value.descriptor, source_kind="https", source="https://cdn.example/refreshed")
            self.assertEqual(first["id"], make_artifact_id("chatgpt", "turn-1", 0))
            self.assertEqual(second["id"], first["id"])
            self.assertEqual(store.get(value.id).created_at, created_at)
            self.assertEqual(store.get(value.id).source, "https://cdn.example/refreshed")

    def test_store_rejects_path_like_artifact_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            self.assertIsNone(store.get("img_..\\escape"))
