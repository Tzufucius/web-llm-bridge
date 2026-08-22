"""Persistent registry for browser bridge sessions.

Only session metadata is persisted here.  Conversation messages, credentials,
cookies, tokens, and other arbitrary caller supplied values are intentionally
not part of the record schema.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
_FIELDS = (
    "version",
    "session_id",
    "tab_id",
    "current_url",
    "created_at",
    "updated_at",
    "sequence",
    "active",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SessionStore:
    """A small JSON-backed session registry.

    ``root_dir`` is injectable to keep tests isolated.  Writes use a temporary
    file in the target directory followed by ``os.replace`` so readers never
    observe a partially written JSON document.
    """

    def __init__(self, root_dir: str | os.PathLike[str] | None = None) -> None:
        default = Path(__file__).resolve().parent / "sessions"
        self.root_dir = Path(root_dir) if root_dir is not None else default
        self.index_path = self.root_dir / "index.json"

    def _read_json(self, path: Path) -> Any | None:
        try:
            with path.open("r", encoding="utf-8") as stream:
                return json.load(stream)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as exc:
            LOGGER.warning("无法读取会话注册表文件 %s: %s", path, exc)
            return None

    def _write_json(self, path: Path, value: Any) -> None:
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

    def _record_path(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
            raise ValueError("session_id 必须是安全的文件名")
        return self.root_dir / f"{session_id}.json"

    def _normalise(self, record: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(record, Mapping) or not record.get("session_id"):
            return None
        result = {key: record[key] for key in _FIELDS if key in record}
        if set(("session_id", "tab_id", "current_url")) - result.keys():
            return None
        result["version"] = SCHEMA_VERSION
        result["active"] = bool(result.get("active", False))
        return result

    def _load_records(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        index = self._read_json(self.index_path)
        candidates: Iterable[Any]
        if isinstance(index, Mapping):
            candidates = index.get("sessions", [])
        elif isinstance(index, list):
            candidates = index
        else:
            candidates = []
        if isinstance(candidates, list):
            for item in candidates:
                if isinstance(item, str):
                    item = {"session_id": item}
                if isinstance(item, Mapping) and item.get("session_id"):
                    try:
                        path = self._record_path(str(item["session_id"]))
                    except ValueError:
                        LOGGER.warning("忽略不安全的会话 ID: %r", item.get("session_id"))
                        continue
                    if path.exists():
                        # A present but damaged record must not be replaced by
                        # stale index data; _read_json already emitted a warning.
                        value = self._read_json(path)
                        record = self._normalise(value) if isinstance(value, Mapping) else None
                    else:
                        record = self._normalise(item)
                    if record:
                        records[record["session_id"]] = record
        # The index is only an accelerator.  Recover records after an index
        # failure or interrupted index write by scanning the individual files.
        try:
            paths = self.root_dir.glob("*.json")
        except OSError:
            paths = ()
        for path in paths:
            if path.name == "index.json":
                continue
            value = self._read_json(path)
            record = self._normalise(value) if isinstance(value, Mapping) else None
            if record:
                records[record["session_id"]] = record
        return records

    def _persist(self, records: Mapping[str, Mapping[str, Any]], sequence: int | None = None) -> None:
        values = sorted(records.values(), key=lambda item: item.get("updated_at", ""), reverse=True)
        next_sequence = sequence if sequence is not None else max((int(item.get("sequence", 0)) for item in values), default=0)
        for record in values:
            self._write_json(self._record_path(str(record["session_id"])), dict(record))
        self._write_json(self.index_path, {"version": SCHEMA_VERSION, "sequence": next_sequence, "sessions": values})

    def list(self) -> list[dict[str, Any]]:
        """Return all valid sessions, newest updates first."""
        records = self._load_records()
        return sorted(records.values(), key=lambda item: item.get("updated_at", ""), reverse=True)

    def get(self, session_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list() if item["session_id"] == session_id), None)

    def create(
        self,
        session_id: str | None = None,
        tab_id: str | int | None = None,
        current_url: str | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        if tab_id is None or current_url is None:
            raise ValueError("tab_id 和 current_url 为必填字段")
        session_id = session_id or uuid.uuid4().hex
        now = _now()
        records = self._load_records()
        sequence = max((int(item.get("sequence", 0)) for item in records.values()), default=0) + 1
        record = {
            "version": SCHEMA_VERSION,
            "session_id": session_id,
            "tab_id": tab_id,
            "current_url": current_url,
            "created_at": now,
            "updated_at": now,
            "sequence": sequence,
            "active": bool(active),
        }
        if record["active"]:
            for item in records.values():
                item["active"] = False
        records[session_id] = record
        self._persist(records, sequence)
        return dict(record)

    def upsert(self, record: Mapping[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
        incoming = dict(record or {})
        incoming.update(fields)
        session_id = incoming.get("session_id")
        if not session_id:
            return self.create(**incoming)
        existing = self.get(str(session_id))
        if existing is None:
            return self.create(**{key: incoming[key] for key in ("session_id", "tab_id", "current_url") if key in incoming}, active=bool(incoming.get("active", True)))
        return self.update(str(session_id), **incoming)

    def update(self, session_id: str, **fields: Any) -> dict[str, Any]:
        records = self._load_records()
        if session_id not in records:
            raise KeyError(session_id)
        record = records[session_id]
        for key in ("tab_id", "current_url", "active"):
            if key in fields:
                record[key] = bool(fields[key]) if key == "active" else fields[key]
        record["updated_at"] = _now()
        if record["active"]:
            for key, item in records.items():
                if key != session_id:
                    item["active"] = False
        self._persist(records)
        return dict(record)

    def mark_active(self, session_id: str, active: bool = True) -> dict[str, Any]:
        return self.update(session_id, active=active)

    def find_by_url(self, current_url: str) -> dict[str, Any] | None:
        return next((item for item in self.list() if item.get("current_url") == current_url), None)

    def deactivate_all(self) -> int:
        records = self._load_records()
        changed = 0
        now = _now()
        for record in records.values():
            if record.get("active"):
                record["active"] = False
                record["updated_at"] = now
                changed += 1
        if changed:
            self._persist(records)
        return changed
