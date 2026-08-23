"""Atomic JSON registry for Artifact descriptors and private source refs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .model import ArtifactRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ArtifactStore:
    def __init__(self, root_dir: str | os.PathLike[str] | None = None) -> None:
        home = Path(os.environ.get("WEB_LLM_BRIDGE_HOME", Path.home() / ".web-llm-bridge"))
        self.root_dir = Path(root_dir) if root_dir is not None else home / "artifacts"

    def _path(self, artifact_id: str) -> Path:
        if not isinstance(artifact_id, str) or not artifact_id.startswith("img_") or "/" in artifact_id or "\\" in artifact_id:
            raise ValueError("artifact_id 无效")
        return self.root_dir / f"{artifact_id}.json"

    def _write(self, path: Path, value: Mapping[str, Any]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=self.root_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def upsert(self, *, session_id: str, provider: str, conversation_url: str, descriptor: Mapping[str, Any], source_kind: str, source: str) -> dict[str, Any]:
        artifact_id = descriptor.get("id")
        if not isinstance(artifact_id, str):
            raise ValueError("Artifact descriptor 缺少 id")
        value = dict(descriptor)
        value.update({"session_id": session_id, "provider": provider, "conversation_url": conversation_url, "source_kind": source_kind, "source": source, "created_at": _now()})
        self._write(self._path(artifact_id), value)
        record = ArtifactRecord.from_json(value)
        if record is None:
            raise ValueError("Artifact descriptor 无效")
        return record.descriptor

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        try:
            value = json.loads(self._path(artifact_id).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return ArtifactRecord.from_json(value) if isinstance(value, dict) else None

    def delete_session(self, session_id: str) -> int:
        removed = 0
        try:
            paths = list(self.root_dir.glob("img_*.json"))
        except OSError:
            return 0
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(value, dict) and value.get("session_id") == session_id:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
