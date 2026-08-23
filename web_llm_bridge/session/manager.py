"""Broker 内部的持久化 provider 会话协调。"""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from uuid import uuid4

from ..errors import RPCError, WebLLMBridgeError
from ..protocol import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT
from ..providers.registry import ProviderRegistry
from ..transport import ExtensionTransport
from .store import SessionStore

try:
    from ..artifacts.store import ArtifactStore
except ImportError:  # 允许在精简安装中使用会话管理
    ArtifactStore = Any  # type: ignore[misc,assignment]

class SessionManager:
    def __init__(self, store: SessionStore | None = None, providers: ProviderRegistry | None = None, transport: ExtensionTransport | None = None, artifacts: Any | None = None) -> None:
        self.store = store or SessionStore()
        self.providers = providers or ProviderRegistry()
        self.transport = transport or ExtensionTransport()
        self.artifacts = artifacts or ArtifactStore()
        self._transport_started = False
        self.lock = asyncio.Lock()
        self._active: dict[str, str] = {}
        for record in self.store.list():
            if record["active"]:
                self._active[record["provider"]] = record["session_id"]

    async def open(self, *, provider: str = "chatgpt", new: bool = False, url: str | None = None, session_id: str | None = None, reopen_on_closed: bool | None = None) -> dict[str, Any]:
        if not isinstance(provider, str) or not provider:
            raise WebLLMBridgeError("provider 参数必须是非空字符串", "INVALID_ARGUMENT")
        if not isinstance(new, bool) or (reopen_on_closed is not None and not isinstance(reopen_on_closed, bool)) or (new and (url is not None or session_id is not None)) or (url is not None and session_id is not None):
            raise WebLLMBridgeError("open 参数组合无效", "INVALID_ARGUMENT")
        async with self.lock:
            runtime = self.providers.get_provider(provider)
            record = self.store.get(session_id, provider) if session_id else None
            if session_id and record is None:
                raise WebLLMBridgeError("Session 不存在", "SESSION_NOT_FOUND")
            if url:
                url = runtime.normalize_url(url)
                record = next((item for item in self.store.list(provider) if item["current_url"] == url), None)
            if not new and record is None and provider in self._active:
                record = self.store.get(self._active[provider], provider)
            target_url = url or (record or {}).get("current_url") or runtime.default_url
            result = await self._open_browser(runtime, target_url, new=new, tab_id=record.get("tab_id") if record and not new else None)
            saved = self.store.upsert(session_id=uuid4().hex if new or record is None else record["session_id"], provider=provider, tab_id=result["tab_id"], current_url=result.get("url", target_url), sequence=(record or {}).get("sequence", 0), active=True, reopen_on_closed=(record or {}).get("reopen_on_closed", False) if reopen_on_closed is None else reopen_on_closed)
            self._active[provider] = saved["session_id"]
            return self._result(saved)

    async def chat(self, text: str, *, provider: str = "chatgpt", session_id: str | None = None, progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        async with self.lock:
            record = await self._ensure(provider, session_id)
            sequence = record["sequence"] + 1
            self.store.upsert(record, sequence=sequence, active=True)
            def on_progress(event: dict[str, Any]) -> None:
                if isinstance(event.get("url"), str):
                    self.store.upsert(record, current_url=event["url"], tab_id=event.get("tab_id", record["tab_id"]), sequence=sequence, active=True)
                if progress:
                    progress(event)
            try:
                result = await self._chat_browser(provider, record["tab_id"], text, on_progress)
            except WebLLMBridgeError as exc:
                if exc.code == "TAB_CLOSED" and record.get("reopen_on_closed") is True:
                    await self._rebind_after_closed(provider, record)
                # 请求可能已经提交，绝不能自动重发，并保留原始错误。
                raise
            saved = self.store.upsert(record, current_url=result.get("url", record["current_url"]), sequence=sequence, active=True)
            response: dict[str, Any] = {**self._result(saved), "text": result["text"]}
            raw_artifacts = result.get("artifacts")
            if isinstance(raw_artifacts, list):
                public_artifacts: list[dict[str, Any]] = []
                for item in raw_artifacts:
                    if not isinstance(item, dict):
                        continue
                    descriptor = {key: value for key, value in item.items() if not key.startswith("_")}
                    source = item.get("_source")
                    source_kind = item.get("_source_kind")
                    if isinstance(source, str) and isinstance(source_kind, str):
                        try:
                            saved_descriptor = self.artifacts.upsert(
                                session_id=saved["session_id"], provider=provider,
                                conversation_url=saved["current_url"], descriptor=descriptor,
                                source_kind=source_kind, source=source,
                            )
                            descriptor = saved_descriptor
                        except (TypeError, ValueError):
                            pass
                    public_artifacts.append(descriptor)
                response["artifacts"] = public_artifacts
            return response

    async def get_messages(self, *, provider: str = "chatgpt", session_id: str | None = None, limit: int | None = DEFAULT_HISTORY_LIMIT, full: bool = False) -> dict[str, Any]:
        async with self.lock:
            record = await self._ensure(provider, session_id)
            runtime = self.providers.get_provider(provider)
            if not isinstance(full, bool) or (not full and limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY_LIMIT)):
                raise WebLLMBridgeError(f"limit 必须是 1 到 {MAX_HISTORY_LIMIT} 的正整数", "INVALID_ARGUMENT")
            try:
                result = await self._history_browser(runtime.id, record["tab_id"], limit=None if full else limit, full=full)
            except WebLLMBridgeError as exc:
                if exc.code != "TAB_CLOSED" or record.get("reopen_on_closed") is not True:
                    raise
                record = await self._rebind_after_closed(provider, record)
                result = await self._history_browser(runtime.id, record["tab_id"], limit=None if full else limit, full=full)
            saved = self.store.upsert(record, current_url=result.get("url", record["current_url"]), active=True)
            return {**self._result(saved), "messages": result["messages"], "truncated": result.get("truncated") is True}

    async def list_sessions(self, provider: str | None = None) -> list[dict[str, Any]]:
        return [dict(item, active=self._active.get(item["provider"]) == item["session_id"]) for item in self.store.list(provider)]

    async def close_session(self, *, provider: str = "chatgpt", session_id: str | None = None) -> dict[str, Any]:
        """解除浏览器标签绑定，但保留会话元数据，重复关闭不报错。"""
        async with self.lock:
            record = self.store.get(session_id, provider) if session_id else self.store.get(self._active.get(provider, ""), provider)
            if record is None:
                raise WebLLMBridgeError("Session 不存在", "SESSION_NOT_FOUND")
            try:
                await self._request_browser("close_session", {"provider": provider, "tab_id": record["tab_id"]}, timeout_ms=30_000)
            except WebLLMBridgeError as exc:
                if exc.code != "TAB_CLOSED":
                    raise
            saved = self.store.upsert(record, active=False)
            if self._active.get(provider) == record["session_id"]:
                self._active.pop(provider, None)
            return self._result(saved)

    async def forget_session(self, *, provider: str = "chatgpt", session_id: str) -> dict[str, Any]:
        async with self.lock:
            record = self.store.get(session_id, provider)
            if record is None:
                raise WebLLMBridgeError("Session 不存在", "SESSION_NOT_FOUND")
            self.store.delete(session_id)
            if self._active.get(provider) == session_id:
                self._active.pop(provider, None)
            delete_artifacts = getattr(self.artifacts, "delete_session", None)
            if delete_artifacts:
                delete_artifacts(session_id)
            return {"session_id": session_id, "provider": provider, "forgotten": True}

    async def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        record = self.artifacts.get(artifact_id)
        if record is None:
            raise WebLLMBridgeError("Artifact 不存在", "ARTIFACT_NOT_FOUND")
        descriptor = getattr(record, "descriptor", record)
        return dict(descriptor)

    async def close(self) -> None:
        async with self.lock:
            await self.transport.close()
            self._transport_started = False

    async def _ensure(self, provider: str, session_id: str | None) -> dict[str, Any]:
        record = self.store.get(session_id, provider) if session_id else self.store.get(self._active.get(provider, ""), provider)
        if record is None:
            runtime = self.providers.get_provider(provider)
            result = await self._open_browser(runtime, runtime.default_url)
            record = self.store.upsert(
                session_id=uuid4().hex,
                provider=provider,
                tab_id=result["tab_id"],
                current_url=result.get("url", runtime.default_url),
                sequence=0,
                active=True,
                reopen_on_closed=False,
            )
            self._active[provider] = record["session_id"]
        assert record is not None
        return record

    async def _rebind_after_closed(self, provider: str, record: dict[str, Any]) -> dict[str, Any]:
        try:
            rebound = await self._open_browser(self.providers.get_provider(provider), record["current_url"], tab_id=record["tab_id"])
        except WebLLMBridgeError:
            return record
        return self.store.upsert(record, tab_id=rebound["tab_id"], current_url=rebound.get("url", record["current_url"]), active=True)

    @staticmethod
    def _result(record: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": record["session_id"], "provider": record["provider"], "tab_id": record["tab_id"], "conversation_url": record["current_url"], "sequence": record["sequence"], "reopen_on_closed": record.get("reopen_on_closed", False)}

    async def _request_browser(self, method: str, params: dict[str, Any], *, timeout_ms: int, progress: Callable[[dict[str, Any]], None] | None = None, reset_on_progress: bool = False) -> dict[str, Any]:
        if not self._transport_started:
            await self.transport.start()
            self._transport_started = True
        try:
            return await self.transport.request(method, params, timeout_ms=timeout_ms, progress_callback=progress, reset_timeout_on_progress=reset_on_progress)
        except RPCError as exc:
            if method == "chat" and exc.code == "RPC_TIMEOUT":
                raise WebLLMBridgeError("等待页面回复超时", "RESPONSE_TIMEOUT") from exc
            raise

    async def _open_browser(self, definition: Any, url: str, *, new: bool = False, tab_id: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"provider": definition.id, "url": definition.normalize_url(url)}
        if new:
            params["new"] = True
        if isinstance(tab_id, int):
            params["tab_id"] = tab_id
        result = await self._request_browser("open", params, timeout_ms=30_000)
        if not isinstance(result.get("tab_id"), int):
            raise WebLLMBridgeError("Extension 未返回有效 tab_id", "INTERNAL_ERROR")
        return result

    async def _chat_browser(self, provider: str, tab_id: int, text: str, progress: Callable[[dict[str, Any]], None] | None) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise WebLLMBridgeError("text 不能为空", "INVALID_ARGUMENT")
        result = await self._request_browser("chat", {"provider": provider, "tab_id": tab_id, "text": text}, timeout_ms=300_000, progress=progress, reset_on_progress=True)
        if not isinstance(result.get("text"), str) or not result["text"].strip():
            raise WebLLMBridgeError("Extension 返回了空回复", "INTERNAL_ERROR")
        return result

    async def _history_browser(self, provider: str, tab_id: int, *, limit: int | None, full: bool) -> dict[str, Any]:
        result = await self._request_browser("get_messages", {"provider": provider, "tab_id": tab_id, "limit": limit, "full": full}, timeout_ms=70_000)
        if not isinstance(result.get("messages"), list):
            raise WebLLMBridgeError("Extension 返回了无效消息列表", "INTERNAL_ERROR")
        return result
