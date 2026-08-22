"""Persistent Broker：集中拥有 Browser Bridge，并提供 Agent NDJSON RPC。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

try:
    from .bridge_core import (
        DEFAULT_HISTORY_LIMIT,
        ERROR_MESSAGES,
        MAX_HISTORY_LIMIT,
        ChatGPTBridgeError,
        ChatGPTSession,
        normalize_conversation_url,
    )
    from .session_store import SessionStore
except ImportError:  # direct script execution
    from bridge_core import (  # type: ignore
        DEFAULT_HISTORY_LIMIT,
        ERROR_MESSAGES,
        MAX_HISTORY_LIMIT,
        ChatGPTBridgeError,
        ChatGPTSession,
        normalize_conversation_url,
    )
    from session_store import SessionStore  # type: ignore


AGENT_HOST = "127.0.0.1"
AGENT_PORT = 8766
AGENT_MAX_LINE_BYTES = 8 * 1024 * 1024
AGENT_DEFAULT_MESSAGE_LIMIT = 5
SESSION_DEFAULT_URL = "https://chatgpt.com/"
LOGGER = logging.getLogger("chatgpt_broker")


class BrokerError(RuntimeError):
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        *,
        safe_to_retry: bool = False,
    ) -> None:
        self.code = code
        self.safe_to_retry = safe_to_retry
        super().__init__(message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _message_for(code: str, fallback: str | None = None) -> str:
    return ERROR_MESSAGES.get(code, fallback or code)


class PersistentChatGPTBroker:
    """所有 Agent 共用的单一 ChatGPTSession owner。"""

    def __init__(
        self,
        *,
        store: SessionStore | None = None,
        session_factory: Any = ChatGPTSession,
    ) -> None:
        self._store = store or SessionStore()
        self._session_factory = session_factory
        self._session: Any | None = None
        self._session_id: str | None = None
        self._operation_lock = asyncio.Lock()
        self._sequence = 0
        self._state = "idle"
        self._progress_sink: Callable[[dict[str, Any]], None] | None = None
        self._restore_active_metadata()

    def _restore_active_metadata(self) -> None:
        records = self._list_records()
        active = next((record for record in records if record.get("active") is True), None)
        if active is None:
            return
        self._session_id = str(active["session_id"])
        self._sequence = int(active.get("sequence") or 0)

    def _list_records(self) -> list[dict[str, Any]]:
        if hasattr(self._store, "list_records"):
            return list(self._store.list_records())
        return list(self._store.list())

    def _get_record(self, session_id: str) -> dict[str, Any] | None:
        return self._store.get(session_id)

    def _save_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if hasattr(self._store, "upsert"):
            return self._store.upsert(record)
        return self._store.save(record)

    def _find_by_url(self, url: str) -> dict[str, Any] | None:
        if hasattr(self._store, "find_by_url"):
            return self._store.find_by_url(url)
        normalized = normalize_conversation_url(url)
        return next(
            (record for record in self._list_records() if record.get("current_url") == normalized),
            None,
        )

    def _deactivate_all(self) -> None:
        if hasattr(self._store, "deactivate_all"):
            self._store.deactivate_all()
            return
        for record in self._list_records():
            record["active"] = False
            self._save_record(record)

    async def _new_session(self, url: str, session_id: str | None = None) -> dict[str, Any]:
        normalized_url = normalize_conversation_url(url)
        if self._session is not None and hasattr(self._session, "_shutdown"):
            await self._session._shutdown()
            self._session = None
        session = await self._session_factory.open(
            normalized_url,
            reopen_on_closed=True,
        )
        self._session = session
        self._session_id = session_id or str(uuid4())
        self._sequence = 0
        now = _utc_now()
        record = {
            "version": 1,
            "session_id": self._session_id,
            "tab_id": getattr(session, "_tab_id", None),
            "current_url": getattr(session, "_current_url", normalized_url),
            "created_at": now,
            "updated_at": now,
            "sequence": 0,
            "active": True,
        }
        self._deactivate_all()
        return self._save_record(record)

    def _current_record(self) -> dict[str, Any] | None:
        return self._get_record(self._session_id) if self._session_id else None

    async def _ensure_session_locked(
        self,
        *,
        session_id: str | None = None,
        url: str | None = None,
        new: bool = False,
    ) -> dict[str, Any]:
        requested_record: dict[str, Any] | None = None
        if session_id is not None:
            requested_record = self._get_record(session_id)
            if requested_record is None:
                raise BrokerError("Session 不存在", "SESSION_NOT_FOUND")
            url = str(requested_record.get("current_url") or SESSION_DEFAULT_URL)
        elif url is not None:
            url = normalize_conversation_url(url)
            if not new:
                requested_record = self._find_by_url(url)
        elif not new and self._session_id is not None:
            requested_record = self._current_record()
            if requested_record is not None:
                url = str(requested_record.get("current_url") or SESSION_DEFAULT_URL)

        if (
            not new
            and requested_record is not None
            and self._session is not None
            and self._session_id == requested_record.get("session_id")
        ):
            return requested_record

        if url is None:
            url = SESSION_DEFAULT_URL
        requested_id = None if new else (requested_record or {}).get("session_id")
        record = await self._new_session(url, requested_id)
        return record

    async def open(
        self,
        *,
        new: bool = False,
        url: str | None = None,
        session_id: str | None = None,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(new, bool):
            raise BrokerError("new 参数必须是布尔值", "INVALID_ARGUMENT")
        if url is not None and not isinstance(url, str):
            raise BrokerError("url 参数必须是字符串", "INVALID_ARGUMENT")
        if session_id is not None and not isinstance(session_id, str):
            raise BrokerError("session_id 参数必须是字符串", "INVALID_ARGUMENT")
        if new and (url is not None or session_id is not None):
            raise BrokerError("new 不能同时指定 url 或 session_id", "INVALID_ARGUMENT")
        if url is not None and session_id is not None:
            raise BrokerError("url 不能同时指定 session_id", "INVALID_ARGUMENT")
        async with self._operation_lock:
            record = await self._ensure_session_locked(
                session_id=session_id,
                url=url,
                new=new,
            )
            self._write_current_metadata(record)
            return self._session_result(record)

    async def get_messages(
        self,
        *,
        limit: int = AGENT_DEFAULT_MESSAGE_LIMIT,
        full: bool = False,
    ) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise BrokerError(
                f"limit 必须是 1 到 {MAX_HISTORY_LIMIT} 的正整数",
                "INVALID_ARGUMENT",
            )
        if not isinstance(full, bool):
            raise BrokerError("full 参数必须是布尔值", "INVALID_ARGUMENT")
        async with self._operation_lock:
            record = await self._ensure_session_locked()
            messages = await self._session.get_messages(
                limit=None if full else limit,
                full=full,
            )
            record = self._refresh_record(record)
            self._save_record(record)
            return {
                "session_id": self._session_id,
                "conversation_url": record.get("current_url"),
                "sequence": self._sequence,
                "messages": messages,
            }

    async def chat(
        self,
        text: str,
        *,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise BrokerError("text 不能为空", "INVALID_ARGUMENT")
        async with self._operation_lock:
            record = await self._ensure_session_locked()
            self._sequence = int(record.get("sequence") or 0) + 1
            record["sequence"] = self._sequence
            self._save_record(record)
            self._state = "chatting"
            previous_callback = getattr(self._session, "_progress_callback", None)

            def handle_progress(event: dict[str, Any]) -> None:
                self._update_from_progress(record, event)
                if progress_sink is not None:
                    progress_sink(event)

            try:
                if hasattr(self._session, "_set_progress_callback"):
                    self._session._set_progress_callback(handle_progress)
                answer = await self._session.chat(text)
            except ChatGPTBridgeError as exc:
                record = self._refresh_record(record)
                self._save_record(record)
                raise BrokerError(str(exc), exc.code, safe_to_retry=exc.safe_to_retry) from exc
            finally:
                self._state = "idle"
                if hasattr(self._session, "_set_progress_callback"):
                    self._session._set_progress_callback(previous_callback)
            record = self._refresh_record(record)
            self._save_record(record)
            return {
                "session_id": self._session_id,
                "conversation_url": record.get("current_url"),
                "sequence": self._sequence,
                "text": answer,
            }

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with self._operation_lock:
            return [
                {
                    "session_id": record.get("session_id"),
                    "conversation_url": record.get("current_url"),
                    "created_at": record.get("created_at"),
                    "updated_at": record.get("updated_at"),
                    "sequence": record.get("sequence", 0),
                    "active": record.get("session_id") == self._session_id,
                }
                for record in self._list_records()
            ]

    def _session_result(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": self._session_id,
            "tab_id": getattr(self._session, "_tab_id", record.get("tab_id")),
            "conversation_url": record.get("current_url"),
            "sequence": self._sequence,
        }

    def _refresh_record(self, record: dict[str, Any]) -> dict[str, Any]:
        record["tab_id"] = getattr(self._session, "_tab_id", record.get("tab_id"))
        current_url = getattr(
            self._session,
            "_current_url",
            record.get("current_url"),
        )
        if isinstance(current_url, str) and current_url:
            try:
                current_url = normalize_conversation_url(current_url)
            except ChatGPTBridgeError:
                pass
            record["current_url"] = current_url
        record["updated_at"] = _utc_now()
        record["active"] = True
        record["sequence"] = self._sequence
        return record

    def _write_current_metadata(self, record: dict[str, Any]) -> None:
        self._save_record(self._refresh_record(record))

    def _update_from_progress(self, record: dict[str, Any], event: dict[str, Any]) -> None:
        current_url = event.get("url")
        if isinstance(current_url, str) and current_url:
            try:
                current_url = normalize_conversation_url(current_url)
            except ChatGPTBridgeError:
                return
            record["current_url"] = current_url
            record["updated_at"] = _utc_now()
            record["tab_id"] = event.get("tab_id", record.get("tab_id"))
            record["sequence"] = self._sequence
            record["active"] = True
            self._save_record(record)

    async def close(self) -> None:
        if self._session is not None and hasattr(self._session, "_shutdown"):
            await self._session._shutdown()
        self._session = None

    async def handle_request(
        self,
        request: dict[str, Any],
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        request_id = request.get("id") if isinstance(request, dict) else None
        method = request.get("method") if isinstance(request, dict) else None
        params = request.get("params", {}) if isinstance(request, dict) else {}
        if not isinstance(request_id, str) or not request_id:
            return self._error_response(request_id, "INVALID_REQUEST", "缺少有效 id")
        if not isinstance(method, str):
            return self._error_response(request_id, "INVALID_REQUEST", "缺少有效 method")
        if not isinstance(params, dict):
            return self._error_response(request_id, "INVALID_ARGUMENT", "params 必须是对象")
        try:
            if method == "open":
                result = await self.open(
                    new=params.get("new", False),
                    url=params.get("url"),
                    session_id=params.get("session_id"),
                )
            elif method == "get_messages":
                result = await self.get_messages(
                    limit=params.get("limit", AGENT_DEFAULT_MESSAGE_LIMIT),
                    full=params.get("full", False),
                )
            elif method == "chat":
                result = await self.chat(params.get("text"), progress_sink=progress_sink)
            elif method == "list_sessions":
                result = {"sessions": await self.list_sessions()}
            else:
                return self._error_response(request_id, "UNKNOWN_METHOD", f"未知方法：{method}")
        except BrokerError as exc:
            return self._error_response(
                request_id,
                exc.code,
                str(exc),
                safe_to_retry=exc.safe_to_retry,
            )
        except ChatGPTBridgeError as exc:
            return self._error_response(
                request_id,
                exc.code,
                str(exc),
                safe_to_retry=exc.safe_to_retry,
            )
        except Exception:
            LOGGER.exception("处理 Broker RPC 失败")
            return self._error_response(request_id, "INTERNAL_ERROR", "Broker 内部错误")
        return {"id": request_id, "ok": True, "result": result}

    @staticmethod
    def _error_response(
        request_id: Any,
        code: str,
        message: str,
        *,
        safe_to_retry: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": request_id,
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "safe_to_retry": safe_to_retry,
            },
        }

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        write_lock = asyncio.Lock()
        request_tasks: set[asyncio.Task[Any]] = set()

        async def send(message: dict[str, Any]) -> None:
            payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            async with write_lock:
                writer.write(payload)
                await writer.drain()

        async def handle_line(raw_line: bytes) -> None:
            try:
                request = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                await send(self._error_response(None, "INVALID_JSON", "请求不是有效 JSON"))
                return
            if not isinstance(request, dict):
                await send(self._error_response(None, "INVALID_REQUEST", "请求必须是 JSON 对象"))
                return
            request_id = request.get("id")

            def progress_sink(event: dict[str, Any]) -> None:
                asyncio.create_task(
                    send(
                        {
                            "type": "progress",
                            "id": request_id,
                            "tab_id": event.get("tab_id"),
                            "url": event.get("url", ""),
                            "phase": event.get("phase"),
                            "elapsed_ms": event.get("elapsed_ms", 0),
                            "idle_ms": event.get("idle_ms", 0),
                        }
                    )
                )

            response = await self.handle_request(request, progress_sink=progress_sink)
            await send(response)

        try:
            while True:
                raw_line = await reader.readline()
                if not raw_line:
                    break
                if len(raw_line) > AGENT_MAX_LINE_BYTES:
                    await send(self._error_response(None, "INVALID_ARGUMENT", "请求行过大"))
                    continue
                task = asyncio.create_task(handle_line(raw_line.rstrip(b"\r\n")))
                request_tasks.add(task)
                task.add_done_callback(request_tasks.discard)
        finally:
            if request_tasks:
                await asyncio.gather(*request_tasks, return_exceptions=True)
            writer.close()
            await writer.wait_closed()

    async def serve_forever(self) -> None:
        server = await asyncio.start_server(self._handle_client, AGENT_HOST, AGENT_PORT)
        LOGGER.info("Persistent Broker 已监听 %s:%s", AGENT_HOST, AGENT_PORT)
        try:
            async with server:
                await server.serve_forever()
        finally:
            server.close()
            await server.wait_closed()
            await self.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChatGPT Persistent Broker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="启动常驻 Broker")
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "serve":
        broker = PersistentChatGPTBroker()
        await broker.serve_forever()
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        return asyncio.run(_async_main(argv))
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        LOGGER.error("Broker 启动失败：%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
