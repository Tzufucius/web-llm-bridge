"""Bounded Artifact materialization without third-party HTTP/image packages."""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
import os
from pathlib import Path
import tempfile
from typing import Any, Awaitable, Callable
from urllib.parse import unquote_to_bytes, urlsplit
from urllib.request import Request, urlopen

from ..errors import WebLLMBridgeError
from .model import ArtifactRecord

MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}


def _mime_from_path(path: Path, declared: str | None) -> str | None:
    if declared in SUPPORTED_MIME_TYPES:
        return declared
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed if guessed in SUPPORTED_MIME_TYPES else None


def _validate_bytes(data: bytes, mime_type: str | None, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> str:
    if len(data) > max_bytes:
        raise WebLLMBridgeError("Artifact 超过大小限制", "ARTIFACT_TOO_LARGE")
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise WebLLMBridgeError("Artifact MIME 类型不受支持", "ARTIFACT_INVALID_TYPE")
    signatures = _MAGIC[mime_type]
    if mime_type == "image/webp":
        valid = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    else:
        valid = any(data.startswith(signature) for signature in signatures)
    if not valid:
        raise WebLLMBridgeError("Artifact 内容与 MIME 类型不匹配", "ARTIFACT_INVALID_TYPE")
    return mime_type


def _data_uri(source: str, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> tuple[str, bytes]:
    header, separator, payload = source.partition(",")
    if separator == "" or not header.lower().startswith("data:"):
        raise WebLLMBridgeError("Artifact data URL 无效", "ARTIFACT_UNAVAILABLE")
    metadata = header[5:].split(";")
    mime_type = metadata[0].lower() if metadata and metadata[0] else None
    if "base64" in {item.lower() for item in metadata[1:]} and len(payload) > ((max_bytes + 2) // 3) * 4:
        raise WebLLMBridgeError("Artifact 超过大小限制", "ARTIFACT_TOO_LARGE")
    try:
        data = base64.b64decode(payload, validate=True) if "base64" in {item.lower() for item in metadata[1:]} else unquote_to_bytes(payload)
    except (ValueError, binascii.Error) as exc:
        raise WebLLMBridgeError("Artifact data URL 编码无效", "ARTIFACT_TRANSFER_FAILED") from exc
    return mime_type or "", data


class ArtifactMaterializer:
    def __init__(self, *, max_bytes: int = MAX_ARTIFACT_BYTES, blob_fetcher: Callable[[ArtifactRecord], Awaitable[bytes | tuple[bytes, str | None]]] | None = None) -> None:
        self.max_bytes = max_bytes
        self.blob_fetcher = blob_fetcher

    async def materialize(self, record: ArtifactRecord, output: str | os.PathLike[str] | None = None) -> dict[str, Any]:
        target = Path(output) if output is not None else self._default_path(record)
        source_kind = record.source_kind.lower()
        try:
            if source_kind == "data" or record.source.startswith("data:"):
                declared, data = _data_uri(record.source, max_bytes=self.max_bytes)
                mime_type = _validate_bytes(data, record.mime_type or declared, max_bytes=self.max_bytes)
            elif source_kind == "blob" or record.source.startswith("blob:"):
                if self.blob_fetcher is None:
                    raise WebLLMBridgeError("Artifact blob 需要 Extension 传输", "ARTIFACT_UNAVAILABLE")
                fetched = await self.blob_fetcher(record)
                transfer_mime: str | None = None
                if isinstance(fetched, tuple):
                    data, transfer_mime = fetched
                else:
                    data = fetched
                mime_type = _validate_bytes(data, record.mime_type or transfer_mime, max_bytes=self.max_bytes)
            elif source_kind == "https" or record.source.startswith("https:"):
                mime_type, data = self._download_https(record.source, record.mime_type)
            else:
                raise WebLLMBridgeError("Artifact 来源不可用", "ARTIFACT_UNAVAILABLE")
            if len(data) > self.max_bytes:
                raise WebLLMBridgeError("Artifact 超过大小限制", "ARTIFACT_TOO_LARGE")
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(data).hexdigest()
            self._atomic_write(target, data)
            return {"id": record.id, "kind": record.kind, "path": str(target.resolve()), "mime_type": mime_type, "size": len(data), "sha256": digest, "quality": record.quality}
        except WebLLMBridgeError:
            raise
        except OSError as exc:
            raise WebLLMBridgeError("Artifact 文件写入失败", "ARTIFACT_WRITE_FAILED") from exc

    def _default_path(self, record: ArtifactRecord) -> Path:
        home = Path(os.environ.get("WEB_LLM_BRIDGE_HOME", Path.home() / ".web-llm-bridge"))
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(record.mime_type or "", ".bin")
        return home / "artifacts" / record.session_id / f"{record.id}{extension}"

    def _download_https(self, source: str, declared: str | None) -> tuple[str, bytes]:
        parsed = urlsplit(source)
        if parsed.scheme != "https" or not parsed.netloc:
            raise WebLLMBridgeError("Artifact 仅支持 HTTPS 来源", "ARTIFACT_UNAVAILABLE")
        try:
            with urlopen(Request(source, headers={"Accept": ",".join(sorted(SUPPORTED_MIME_TYPES))}), timeout=30) as response:
                get_url = getattr(response, "geturl", None)
                final_url = str(get_url() if callable(get_url) else source)
                if urlsplit(final_url).scheme != "https":
                    raise WebLLMBridgeError("Artifact 下载重定向到非 HTTPS 来源", "ARTIFACT_UNAVAILABLE")
                content_type = str(response.headers.get_content_type() or "").lower()
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise WebLLMBridgeError("Artifact 超过大小限制", "ARTIFACT_TOO_LARGE")
                    chunks.append(chunk)
        except WebLLMBridgeError:
            raise
        except OSError as exc:
            raise WebLLMBridgeError("Artifact 下载失败", "ARTIFACT_TRANSFER_FAILED") from exc
        data = b"".join(chunks)
        return _validate_bytes(data, declared or content_type, max_bytes=self.max_bytes), data

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
