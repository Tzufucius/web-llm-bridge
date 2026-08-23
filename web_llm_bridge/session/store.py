"""JSON 会话元数据存储，默认放在用户目录。"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 2
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _is_safe_session_id(value: object) -> bool:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        return False
    if value[-1] in {" ", "."} or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in value):
        return False
    return value.split(".", 1)[0].upper() not in _WINDOWS_RESERVED_NAMES


class SessionStore:
    def __init__(self, sessions_dir: str | os.PathLike[str] | None = None, *, root_dir: str | os.PathLike[str] | None = None) -> None:
        """默认将元数据放在 Bridge Home 下的 sessions 目录。"""
        if sessions_dir is not None and root_dir is not None:
            raise ValueError("sessions_dir 和 root_dir 不能同时指定")
        explicit_dir = sessions_dir if sessions_dir is not None else root_dir
        home = Path(os.environ.get("WEB_LLM_BRIDGE_HOME", Path.home() / ".web-llm-bridge"))
        self.root_dir = Path(explicit_dir) if explicit_dir is not None else home / "sessions"
        self.index_path = self.root_dir / "index.json"

    def _read(self, path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def _write(self, path: Path, value: Any) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=self.root_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _path(self, session_id: str) -> Path:
        if not _is_safe_session_id(session_id):
            raise ValueError("session_id 必须是安全的文件名")
        return self.root_dir / f"{session_id}.json"

    def _normalise(self, source: Mapping[str, Any]) -> dict[str, Any] | None:
        session_id = source.get("session_id")
        tab_id = source.get("tab_id")
        url = source.get("current_url", source.get("conversation_url"))
        if (
            not _is_safe_session_id(session_id)
            or tab_id is None
            or not isinstance(url, str)
        ):
            return None
        try:
            sequence = int(source.get("sequence", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return None
        if isinstance(tab_id, bool) or not isinstance(tab_id, int) or sequence < 0:
            return None
        provider = source.get("provider", "chatgpt")
        if not isinstance(provider, str) or not provider:
            return None
        now = _now()
        created_at = source.get("created_at", now)
        updated_at = source.get("updated_at", now)
        if not isinstance(created_at, str) or not isinstance(updated_at, str):
            return None
        return {"version": SCHEMA_VERSION, "provider": provider, "session_id": session_id, "tab_id": tab_id, "current_url": url, "created_at": created_at, "updated_at": updated_at, "sequence": sequence, "active": bool(source.get("active", False))}

    def _records(self) -> dict[str, dict[str, Any]]:
        candidates: list[Any] = []
        index = self._read(self.index_path)
        if isinstance(index, dict):
            candidates.extend(index.get("sessions", []))
        elif isinstance(index, list):  # v1 兼容
            candidates.extend(index)
        try:
            candidates.extend(self._read(path) for path in self.root_dir.glob("*.json") if path.name != "index.json")
        except OSError:
            pass
        records: dict[str, dict[str, Any]] = {}
        rewrite = False
        for candidate in candidates:
            if isinstance(candidate, Mapping) and "reopen_on_closed" in candidate:
                rewrite = True
            record = self._normalise(candidate) if isinstance(candidate, Mapping) else None
            if record:
                records[record["session_id"]] = record
        if rewrite and records:
            self._persist(records)
        return records

    def _persist(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        values = sorted(records.values(), key=lambda item: str(item.get("updated_at", "")), reverse=True)
        for record in values:
            self._write(self._path(str(record["session_id"])), dict(record))
        self._write(self.index_path, {"version": SCHEMA_VERSION, "sessions": values})

    def list(self, provider: str | None = None) -> list[dict[str, Any]]:
        values = self._records().values()
        if provider:
            values = (item for item in values if item["provider"] == provider)
        return sorted((dict(item) for item in values), key=lambda item: item["updated_at"], reverse=True)

    def get(self, session_id: str, provider: str | None = None) -> dict[str, Any] | None:
        record = self._records().get(session_id)
        return dict(record) if record and (provider is None or record["provider"] == provider) else None

    def upsert(self, record: Mapping[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
        incoming = dict(record or {})
        incoming.update(fields)
        incoming.setdefault("session_id", uuid.uuid4().hex)
        records = self._records()
        existing = records.get(str(incoming["session_id"]))
        merged = dict(existing or {})
        merged.update(incoming)
        if existing is None:
            merged.setdefault("created_at", _now())
        merged["updated_at"] = _now()
        normalised = self._normalise(merged)
        if normalised is None:
            raise ValueError("session_id、tab_id 和 current_url 为必填字段")
        if normalised["active"]:
            for item in records.values():
                if item["provider"] == normalised["provider"]:
                    item["active"] = False
        records[normalised["session_id"]] = normalised
        self._persist(records)
        return dict(normalised)

    def create(self, session_id: str | None = None, tab_id: str | int | None = None, current_url: str | None = None, active: bool = True, provider: str = "chatgpt") -> dict[str, Any]:
        return self.upsert(session_id=session_id or uuid.uuid4().hex, tab_id=tab_id, current_url=current_url, active=active, provider=provider)

    def update(self, session_id: str, **fields: Any) -> dict[str, Any]:
        existing = self.get(session_id)
        if existing is None:
            raise KeyError(session_id)
        return self.upsert(existing, **fields)

    def delete(self, session_id: str) -> bool:
        """删除持久化会话，并原子重写索引；删除不存在的会话是幂等的。"""
        records = self._records()
        if session_id not in records:
            # 即使记录已损坏或仅残留在磁盘，也清理受控的目标路径。
            try:
                self._path(session_id).unlink()
            except (OSError, ValueError):
                pass
            if self.index_path.exists():
                self._persist(records)
            return False
        records.pop(session_id, None)
        try:
            self._path(session_id).unlink()
        except FileNotFoundError:
            pass
        self._persist(records)
        return True

    def deactivate_all(self) -> int:
        records = self._records()
        changed = 0
        for record in records.values():
            if record["active"]:
                record["active"] = False
                record["updated_at"] = _now()
                changed += 1
        if changed:
            self._persist(records)
        return changed
