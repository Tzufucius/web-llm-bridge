"""Broker 内部的持久化 Provider 会话协调。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..artifacts.downloader import ArtifactMaterializer
from ..artifacts.model import ArtifactRecord, make_artifact_id
from ..artifacts.store import ArtifactStore
from ..browser.launcher import BrowserBootstrap
from ..errors import RPCError, WebLLMBridgeError
from ..protocol import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT, error_message
from ..providers.registry import ProviderRegistry
from ..transport import ExtensionTransport
from .store import SessionStore


ARTIFACT_TRANSFER_TIMEOUT_MS = 120_000


class SessionManager:
    def __init__(
        self,
        store: SessionStore | None = None,
        providers: ProviderRegistry | None = None,
        transport: ExtensionTransport | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self.store = store or SessionStore()
        self.providers = providers or ProviderRegistry()
        self.transport = transport or ExtensionTransport()
        self.artifacts = artifacts or ArtifactStore()
        self._browser_bootstrap = BrowserBootstrap(self.transport)
        self.lock = asyncio.Lock()
        # Active bindings belong to this Broker process; a restart must not
        # silently revive a tab from persisted metadata.
        self.store.deactivate_all()
        self._active: dict[str, str] = {}

    async def open(
        self,
        *,
        provider: str = "chatgpt",
        new: bool = False,
        url: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(provider, str) or not provider:
            raise WebLLMBridgeError("provider 参数必须是非空字符串", "INVALID_ARGUMENT")
        if (
            not isinstance(new, bool)
            or (new and (url is not None or session_id is not None))
            or (url is not None and session_id is not None)
        ):
            raise WebLLMBridgeError("open 参数组合无效", "INVALID_ARGUMENT")

        async with self.lock:
            runtime = self.providers.get_provider(provider)
            record = self.store.get(session_id, provider) if session_id else None
            if session_id and record is None:
                raise WebLLMBridgeError("Session 不存在", "SESSION_NOT_FOUND")
            if url:
                url = runtime.normalize_url(url)
                record = next(
                    (item for item in self.store.list(provider) if item["current_url"] == url),
                    None,
                )
            if not new and record is None and provider in self._active:
                record = self.store.get(self._active[provider], provider)

            target_url = url or (record or {}).get("current_url") or runtime.default_url
            result = await self._open_browser(
                runtime,
                target_url,
                new=new,
                tab_id=record.get("tab_id") if record and not new else None,
            )
            saved = self.store.upsert(
                session_id=uuid4().hex if new or record is None else record["session_id"],
                provider=provider,
                tab_id=result["tab_id"],
                current_url=result.get("url", target_url),
                sequence=(record or {}).get("sequence", 0),
                active=True,
            )
            self._active[provider] = saved["session_id"]
            return self._result(saved)

    async def chat(
        self,
        text: str,
        *,
        provider: str = "chatgpt",
        session_id: str | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        async with self.lock:
            record = await self._ensure_bound_session(provider, session_id)
            sequence = record["sequence"] + 1
            current = self.store.upsert(record, sequence=sequence, active=True)

            def on_progress(event: dict[str, Any]) -> None:
                nonlocal current
                if isinstance(event.get("url"), str):
                    current = self.store.upsert(
                        current,
                        current_url=event["url"],
                        tab_id=event.get("tab_id", current["tab_id"]),
                        sequence=sequence,
                        active=True,
                    )
                if progress:
                    progress(event)

            result = await self._chat_browser(provider, current["tab_id"], text, on_progress)
            saved = self.store.upsert(
                current,
                tab_id=result.get("tab_id", current["tab_id"]),
                current_url=result.get("url", current["current_url"]),
                sequence=sequence,
                active=True,
            )
            return {
                **self._result(saved),
                "text": result["text"],
                "artifacts": self._persist_artifacts(saved, result.get("artifacts")),
            }

    async def get_messages(
        self,
        *,
        provider: str = "chatgpt",
        session_id: str | None = None,
        limit: int | None = DEFAULT_HISTORY_LIMIT,
        full: bool = False,
    ) -> dict[str, Any]:
        async with self.lock:
            record = await self._ensure_bound_session(provider, session_id)
            runtime = self.providers.get_provider(provider)
            if not isinstance(full, bool) or (
                not full
                and limit is not None
                and (
                    isinstance(limit, bool)
                    or not isinstance(limit, int)
                    or not 1 <= limit <= MAX_HISTORY_LIMIT
                )
            ):
                raise WebLLMBridgeError(
                    f"limit 必须是 1 到 {MAX_HISTORY_LIMIT} 的正整数",
                    "INVALID_ARGUMENT",
                )

            result = await self._history_browser(
                runtime.id,
                record["tab_id"],
                limit=None if full else limit,
                full=full,
            )
            saved = self.store.upsert(
                record,
                tab_id=result.get("tab_id", record["tab_id"]),
                current_url=result.get("url", record["current_url"]),
                active=True,
            )
            messages = []
            for message in result["messages"]:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                content = message.get("content")
                if not isinstance(role, str) or not isinstance(content, str):
                    continue
                messages.append(
                    {
                        "role": role,
                        "content": content,
                        "artifacts": self._persist_artifacts(saved, message.get("artifacts")),
                    }
                )
            return {
                **self._result(saved),
                "messages": messages,
                "truncated": result.get("truncated") is True,
            }

    async def list_sessions(self, provider: str | None = None) -> list[dict[str, Any]]:
        return [self._result(item) for item in self.store.list(provider)]

    async def close_session(self, *, provider: str = "chatgpt", session_id: str) -> dict[str, Any]:
        """关闭绑定标签页但保留 Session 元数据；重复关闭保持幂等。"""
        if not isinstance(session_id, str) or not session_id:
            raise WebLLMBridgeError("session_id 参数为必填字符串", "INVALID_ARGUMENT")
        async with self.lock:
            record = self.store.get(session_id, provider)
            if record is None:
                raise WebLLMBridgeError("Session 不存在", "SESSION_NOT_FOUND")
            await self._close_tab_if_present(record.get("tab_id"))
            saved = self.store.upsert(record, active=False)
            if self._active.get(provider) == session_id:
                self._active.pop(provider, None)
            return self._result(saved)

    async def forget_session(self, *, provider: str = "chatgpt", session_id: str) -> dict[str, Any]:
        if not isinstance(session_id, str) or not session_id:
            raise WebLLMBridgeError("session_id 参数为必填字符串", "INVALID_ARGUMENT")
        async with self.lock:
            record = self.store.get(session_id, provider)
            if record is None:
                raise WebLLMBridgeError("Session 不存在", "SESSION_NOT_FOUND")
            await self._close_tab_if_present(record.get("tab_id"))
            self.store.delete(session_id)
            if self._active.get(provider) == session_id:
                self._active.pop(provider, None)
            self.artifacts.delete_session(session_id)
            return {"session_id": session_id, "provider": provider, "forgotten": True}

    async def get_artifact(
        self,
        artifact_id: str,
        *,
        output: str | Path | None = None,
    ) -> dict[str, Any]:
        if not isinstance(artifact_id, str) or not artifact_id:
            raise WebLLMBridgeError("artifact_id 参数必须是非空字符串", "INVALID_ARGUMENT")
        async with self.lock:
            record = self.artifacts.get(artifact_id)
            if record is None:
                raise WebLLMBridgeError("Artifact 不存在", "ARTIFACT_NOT_FOUND")

            working_tab: int | None = None
            temporary_tab: int | None = None

            async def fetch_browser(current: ArtifactRecord, *, retry_after_tab_close: bool = True) -> bytes | tuple[bytes, str | None]:
                nonlocal working_tab, temporary_tab
                if working_tab is None:
                    working_tab, temporary = await self._bind_artifact_tab(current)
                    if temporary:
                        temporary_tab = working_tab
                try:
                    result = await self._request_browser(
                        "get_artifact",
                        {
                            "provider": current.provider,
                            "tab_id": working_tab,
                            "artifact": {
                                **current.descriptor,
                                "_source": current.source,
                                "_source_kind": current.source_kind,
                            },
                        },
                        timeout_ms=ARTIFACT_TRANSFER_TIMEOUT_MS,
                    )
                except WebLLMBridgeError as exc:
                    if exc.code != "TAB_CLOSED":
                        raise
                    working_tab = None
                    if temporary_tab is not None:
                        await self._close_tab_if_present(temporary_tab)
                        temporary_tab = None
                    if not retry_after_tab_close:
                        raise
                    return await fetch_browser(current, retry_after_tab_close=False)

                data = result.get("_artifact_bytes")
                if not isinstance(data, (bytes, bytearray)):
                    raise WebLLMBridgeError("Artifact 分块传输结果无效", "ARTIFACT_TRANSFER_FAILED")
                source = result.get("_source")
                source_kind = result.get("_source_kind")
                if isinstance(source, str) and isinstance(source_kind, str):
                    self.artifacts.upsert(
                        session_id=current.session_id,
                        provider=current.provider,
                        conversation_url=current.conversation_url,
                        descriptor=current.descriptor,
                        source_kind=source_kind,
                        source=source,
                    )
                transfer_mime = result.get("_artifact_mime_type")
                return bytes(data), transfer_mime if isinstance(transfer_mime, str) else None

            try:
                materializer = ArtifactMaterializer(
                    blob_fetcher=fetch_browser,
                    https_fetcher=fetch_browser,
                )
                return await materializer.materialize(record, output)
            finally:
                if temporary_tab is not None:
                    await self._close_tab_if_present(temporary_tab)

    async def close(self) -> None:
        async with self.lock:
            await self.transport.close()

    async def _ensure_bound_session(self, provider: str, session_id: str | None) -> dict[str, Any]:
        runtime = self.providers.get_provider(provider)
        record = self.store.get(session_id, provider) if session_id else self.store.get(self._active.get(provider, ""), provider)
        if session_id and record is None:
            raise WebLLMBridgeError("Session 不存在", "SESSION_NOT_FOUND")
        if record is None:
            result = await self._open_browser(runtime, runtime.default_url)
            record = self.store.upsert(
                session_id=uuid4().hex,
                provider=provider,
                tab_id=result["tab_id"],
                current_url=result.get("url", runtime.default_url),
                sequence=0,
                active=True,
            )
        else:
            rebound = await self._open_browser(
                runtime,
                record["current_url"],
                tab_id=record.get("tab_id"),
            )
            record = self.store.upsert(
                record,
                tab_id=rebound["tab_id"],
                current_url=rebound.get("url", record["current_url"]),
                active=True,
            )
        self._active[provider] = record["session_id"]
        return record

    async def _bind_artifact_tab(self, record: ArtifactRecord) -> tuple[int, bool]:
        browser_record = self.store.get(record.session_id, record.provider)
        if browser_record is None:
            raise WebLLMBridgeError("Artifact 所属 Session 不存在", "ARTIFACT_NOT_FOUND")
        runtime = self.providers.get_provider(record.provider)
        result = await self._open_browser(
            runtime,
            browser_record["current_url"],
            tab_id=browser_record.get("tab_id"),
        )
        if browser_record.get("active") is True:
            self.store.upsert(
                browser_record,
                tab_id=result["tab_id"],
                current_url=result.get("url", browser_record["current_url"]),
                active=True,
            )
            self._active[record.provider] = record.session_id
            return result["tab_id"], False
        return result["tab_id"], True

    async def _close_tab_if_present(self, tab_id: object) -> None:
        if not isinstance(tab_id, int) or isinstance(tab_id, bool):
            return
        try:
            await self._request_browser("close_tab", {"tab_id": tab_id}, timeout_ms=30_000)
        except WebLLMBridgeError as exc:
            if exc.code != "TAB_CLOSED":
                raise

    @staticmethod
    def _result(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": record["session_id"],
            "provider": record["provider"],
            "conversation_url": record["current_url"],
            "sequence": record["sequence"],
        }

    async def _request_browser(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_ms: int,
        progress: Callable[[dict[str, Any]], None] | None = None,
        reset_on_progress: bool = False,
    ) -> dict[str, Any]:
        if hasattr(self.transport, "connected") and hasattr(self.transport, "wait_until_ready"):
            await self._browser_bootstrap.start("about:blank")
        else:
            await self.transport.start()
        try:
            return await self.transport.request(
                method,
                params,
                timeout_ms=timeout_ms,
                progress_callback=progress,
                reset_timeout_on_progress=reset_on_progress,
            )
        except RPCError as exc:
            if method == "chat" and exc.code in {
                "EXTENSION_NOT_CONNECTED",
                "CONTENT_SCRIPT_UNAVAILABLE",
                "TAB_CLOSED",
            }:
                raise WebLLMBridgeError(
                    error_message("CHAT_STATE_UNKNOWN"),
                    "CHAT_STATE_UNKNOWN",
                ) from exc
            if method == "chat" and exc.code == "RPC_TIMEOUT":
                raise WebLLMBridgeError("等待页面回复超时", "RESPONSE_TIMEOUT") from exc
            raise

    async def _open_browser(
        self,
        definition: Any,
        url: str,
        *,
        new: bool = False,
        tab_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "provider": definition.id,
            "url": definition.normalize_url(url),
        }
        if new:
            params["new"] = True
        if isinstance(tab_id, int):
            params["tab_id"] = tab_id
        result = await self._request_browser("open", params, timeout_ms=30_000)
        if not isinstance(result.get("tab_id"), int):
            raise WebLLMBridgeError("Extension 未返回有效 tab_id", "INTERNAL_ERROR")
        return result

    async def _chat_browser(
        self,
        provider: str,
        tab_id: int,
        text: str,
        progress: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise WebLLMBridgeError("text 不能为空", "INVALID_ARGUMENT")
        result = await self._request_browser(
            "chat",
            {"provider": provider, "tab_id": tab_id, "text": text},
            timeout_ms=300_000,
            progress=progress,
            reset_on_progress=True,
        )
        artifacts = result.get("artifacts")
        if not isinstance(result.get("text"), str) or (
            not result["text"].strip() and (not isinstance(artifacts, list) or not artifacts)
        ):
            raise WebLLMBridgeError("Extension 返回了空回复", "INTERNAL_ERROR")
        return result

    async def _history_browser(
        self,
        provider: str,
        tab_id: int,
        *,
        limit: int | None,
        full: bool,
    ) -> dict[str, Any]:
        result = await self._request_browser(
            "get_messages",
            {"provider": provider, "tab_id": tab_id, "limit": limit, "full": full},
            timeout_ms=70_000,
        )
        if not isinstance(result.get("messages"), list):
            raise WebLLMBridgeError("Extension 返回了无效消息列表", "INTERNAL_ERROR")
        return result

    def _persist_artifacts(self, session: dict[str, Any], raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        public: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            turn_id = item.get("turn_id")
            index = item.get("index")
            if (
                not isinstance(turn_id, str)
                or not turn_id
                or isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
            ):
                continue
            descriptor = {
                key: item[key]
                for key in ("kind", "mime_type", "width", "height", "alt", "quality")
                if key in item
            }
            descriptor.update(
                {
                    "id": make_artifact_id(session["provider"], turn_id, index),
                    "provider": session["provider"],
                    "turn_id": turn_id,
                    "index": index,
                }
            )
            existing = self.artifacts.get(descriptor["id"])
            source = item.get("_source") if isinstance(item.get("_source"), str) and item.get("_source") else (existing.source if existing else "")
            source_kind = item.get("_source_kind") if isinstance(item.get("_source_kind"), str) and item.get("_source_kind") else (existing.source_kind if existing else "")
            try:
                saved = self.artifacts.upsert(
                    session_id=session["session_id"],
                    provider=session["provider"],
                    conversation_url=session["current_url"],
                    descriptor=descriptor,
                    source_kind=source_kind,
                    source=source,
                )
            except (TypeError, ValueError):
                continue
            public.append(saved)
        return public
