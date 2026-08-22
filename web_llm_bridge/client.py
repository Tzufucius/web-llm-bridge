"""面向 Broker 的 NDJSON RPC 客户端。"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable
from uuid import uuid4

from .errors import WebLLMBridgeError
from .protocol import BRIDGE_HOST, BROKER_PORT, MAX_MESSAGE_BYTES


class WebLLMClient:
    """到本机 Broker 的轻量 RPC 客户端。"""

    def __init__(self, host: str = BRIDGE_HOST, port: int = BROKER_PORT) -> None:
        self.host = host
        self.port = port

    async def call(self, method: str, params: dict[str, Any], *, progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        return await rpc_call(method, params, progress=progress, host=self.host, port=self.port)

    async def open(self, *, provider: str = "chatgpt", new: bool = False, url: str | None = None, session_id: str | None = None, reopen_on_closed: bool | None = None) -> dict[str, Any]:
        return await self.call("open", {"provider": provider, "new": new, "url": url, "session_id": session_id, "reopen_on_closed": reopen_on_closed})

    async def list_sessions(self, *, provider: str | None = None) -> list[dict[str, Any]]:
        result = await self.call("list_sessions", {"provider": provider} if provider else {})
        sessions = result.get("sessions")
        if not isinstance(sessions, list):
            raise WebLLMBridgeError("Broker 返回无效会话列表", "INVALID_RESPONSE")
        return sessions


async def rpc_call(method: str, params: dict[str, Any], *, progress: Callable[[dict[str, Any]], None] | None = None, host: str = BRIDGE_HOST, port: int = BROKER_PORT) -> dict[str, Any]:
    request_id = str(uuid4())
    reader, writer = await asyncio.open_connection(host, port, limit=MAX_MESSAGE_BYTES + 1)
    try:
        writer.write((json.dumps({"id": request_id, "method": method, "params": params}, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        while True:
            try:
                line = await reader.readline()
            except ValueError as exc:
                raise WebLLMBridgeError("Broker 响应行过大", "INVALID_RESPONSE") from exc
            if not line:
                raise ConnectionError("Broker 在返回结果前断开连接")
            message = json.loads(line.decode("utf-8"))
            if message.get("type") == "progress" and message.get("id") == request_id:
                if progress:
                    progress(message)
                continue
            if message.get("id") == request_id:
                if message.get("ok") is not True:
                    error = message.get("error") or {}
                    raise WebLLMBridgeError(str(error.get("message", "Broker 请求失败")), str(error.get("code", "INTERNAL_ERROR")), safe_to_retry=error.get("safe_to_retry") is True)
                result = message.get("result")
                if not isinstance(result, dict):
                    raise WebLLMBridgeError("Broker 返回无效结果", "INVALID_RESPONSE")
                return result
    finally:
        writer.close()
        await writer.wait_closed()
