"""Serializable Artifact metadata and stable identity helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping


def make_artifact_id(provider: str, turn_id: str, index: int) -> str:
    """Build an id independent of expiring signed URLs."""
    identity = f"{provider}\x00{turn_id}\x00{index}".encode("utf-8")
    return f"img_{hashlib.sha256(identity).hexdigest()[:24]}"


@dataclass(frozen=True)
class ArtifactRecord:
    """Public descriptor plus private registry fields.

    ``source`` is intentionally not part of :meth:`descriptor`; it can contain
    a signed URL or a page-local blob reference and must stay local.
    """

    id: str
    kind: str
    provider: str
    session_id: str
    conversation_url: str
    turn_id: str
    index: int
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    alt: str = ""
    quality: str = "unknown"
    source_kind: str = ""
    source: str = ""
    created_at: str = ""

    @property
    def descriptor(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "provider": self.provider,
            "turn_id": self.turn_id,
            "index": self.index,
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "alt": self.alt,
            "quality": self.quality,
        }
        return value

    def to_json(self) -> dict[str, Any]:
        value = self.descriptor
        value.update(
            {
                "session_id": self.session_id,
                "conversation_url": self.conversation_url,
                "source_kind": self.source_kind,
                "source": self.source,
                "created_at": self.created_at,
            }
        )
        return value

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ArtifactRecord | None":
        required = ("id", "kind", "provider", "session_id", "conversation_url", "turn_id", "index")
        if not all(isinstance(value.get(key), str) and value.get(key) for key in required[:-1]):
            return None
        if isinstance(value.get("index"), bool) or not isinstance(value.get("index"), int) or value["index"] < 0:
            return None
        return cls(
            id=str(value["id"]),
            kind=str(value["kind"]),
            provider=str(value["provider"]),
            session_id=str(value["session_id"]),
            conversation_url=str(value["conversation_url"]),
            turn_id=str(value["turn_id"]),
            index=int(value["index"]),
            mime_type=value.get("mime_type") if isinstance(value.get("mime_type"), str) else None,
            width=value.get("width") if isinstance(value.get("width"), int) else None,
            height=value.get("height") if isinstance(value.get("height"), int) else None,
            alt=str(value.get("alt") or ""),
            quality=str(value.get("quality") or "unknown"),
            source_kind=str(value.get("source_kind") or ""),
            source=str(value.get("source") or ""),
            created_at=str(value.get("created_at") or ""),
        )
