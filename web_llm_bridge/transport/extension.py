"""由 Broker 独占的 :8765 Extension JSON-RPC transport。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from typing import Any, Callable
from uuid import uuid4

import websockets
try:
    from websockets.asyncio.server import serve
except ImportError:  # websockets 旧版本兼容
    from websockets import serve
from websockets.exceptions import ConnectionClosed

from ..errors import RPCError, WebLLMBridgeError
from ..protocol import BRIDGE_HOST, EXTENSION_PORT, MAX_MESSAGE_BYTES, PROGRESS_PHASES, PROTOCOL_VERSION, error_message
from ..artifacts.downloader import MAX_ARTIFACT_BYTES

_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


class ExtensionTransport:
    """Broker 生命周期内仅有一个实例，唯一监听 Extension 端口。"""

    def __init__(self) -> None:
        self._server: Any | None = None
        self._client: Any | None = None
        self._ready = asyncio.Event()
        self._connection_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._callbacks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._progress_events: dict[str, asyncio.Event] = {}
        self._artifact_transfers: dict[str, dict[str, Any]] = {}
        self._closed = False

    @property
    def connected(self) -> bool:
        """当前是否存在已完成 hello 握手的扩展连接。"""
        return not self._closed and self._client is not None and self._ready.is_set()

    async def wait_until_ready(self, timeout: float = 60.0) -> None:
        """等待扩展完成握手；超时转换为稳定的 RPC 错误。"""
        if self.connected:
            return
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=max(0.0, timeout))
        except asyncio.TimeoutError as exc:
            raise RPCError(error_message("EXTENSION_HANDSHAKE_TIMEOUT"), "EXTENSION_HANDSHAKE_TIMEOUT", safe_to_retry=True) from exc
        if not self.connected:
            raise RPCError(error_message("EXTENSION_NOT_CONNECTED"), "EXTENSION_NOT_CONNECTED", safe_to_retry=True)

    async def start(self) -> None:
        if self._server is not None:
            return
        self._closed = False
        try:
            self._server = await serve(self._handle_connection, BRIDGE_HOST, EXTENSION_PORT, ping_interval=None, max_size=MAX_MESSAGE_BYTES, origins=[_ORIGIN])
        except OSError as exc:
            raise WebLLMBridgeError(f"无法监听 {BRIDGE_HOST}:{EXTENSION_PORT}", "INTERNAL_ERROR") from exc

    async def close(self) -> None:
        self._closed = True
        self._ready.clear()
        self._fail_pending(RPCError("Bridge 已关闭", "EXTENSION_NOT_CONNECTED"))
        if self._client is not None:
            try:
                await self._client.close()
            except (ConnectionClosed, OSError):
                pass
            self._client = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def request(self, method: str, params: dict[str, Any], *, timeout_ms: int = 30_000, progress_callback: Callable[[dict[str, Any]], None] | None = None, reset_timeout_on_progress: bool = False) -> dict[str, Any]:
        if self._closed:
            raise RPCError("Bridge 已关闭", "EXTENSION_NOT_CONNECTED")
        try:
            await self.wait_until_ready(30)
        except RPCError:
            raise
        request_id = str(uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        if progress_callback:
            self._callbacks[request_id] = progress_callback
        progress_event = asyncio.Event() if reset_timeout_on_progress else None
        if progress_event:
            self._progress_events[request_id] = progress_event
        if method == "get_artifact":
            self._artifact_transfers[request_id] = {"expected": None, "mime_type": None, "next_sequence": 0, "data": bytearray(), "error": None, "ended": False, "done": asyncio.Event()}
        transfer: dict[str, Any] | None = None
        try:
            try:
                async with self._send_lock:
                    if self._client is None:
                        raise RPCError(error_message("EXTENSION_NOT_CONNECTED"), "EXTENSION_NOT_CONNECTED")
                    await self._client.send(json.dumps({"type": "request", "id": request_id, "method": method, "params": params}, ensure_ascii=False))
                response = await self._wait(future, progress_event, timeout_ms)
                transfer = self._artifact_transfers.get(request_id)
            except asyncio.TimeoutError as exc:
                raise RPCError(error_message("RPC_TIMEOUT"), "RPC_TIMEOUT") from exc
            if response.get("type") != "response" or response.get("id") != request_id:
                raise RPCError("Extension 返回了无效 RPC 响应")
            if response.get("ok") is not True:
                error = response.get("error") if isinstance(response.get("error"), dict) else {}
                raise RPCError(str(error.get("message") or error_message(str(error.get("code", "INTERNAL_ERROR")))), str(error.get("code", "INTERNAL_ERROR")), safe_to_retry=error.get("safe_to_retry") is True)
            result = response.get("result")
            if not isinstance(result, dict):
                raise RPCError("Extension 返回了无效结果")
            if transfer:
                done = transfer.get("done")
                if isinstance(done, asyncio.Event) and not done.is_set():
                    try:
                        await asyncio.wait_for(done.wait(), timeout=max(1, timeout_ms) / 1000)
                    except asyncio.TimeoutError as exc:
                        raise RPCError("Artifact 分块传输超时", "ARTIFACT_TRANSFER_FAILED", safe_to_retry=True) from exc
                if transfer.get("error"):
                    raise transfer["error"]
                data = bytes(transfer.get("data", b""))
                expected = transfer.get("expected")
                if expected is None or expected != len(data):
                    raise RPCError("Artifact 分块不完整", "ARTIFACT_TRANSFER_FAILED", safe_to_retry=True)
                result = dict(result)
                result["_artifact_bytes"] = data
                result["_artifact_mime_type"] = transfer.get("mime_type")
            return result
        finally:
            self._pending.pop(request_id, None)
            self._callbacks.pop(request_id, None)
            self._progress_events.pop(request_id, None)
            self._artifact_transfers.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def _wait(self, future: asyncio.Future[dict[str, Any]], progress: asyncio.Event | None, timeout_ms: int) -> dict[str, Any]:
        if progress is None:
            return await asyncio.wait_for(asyncio.shield(future), timeout_ms / 1000)
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while True:
            waiter = asyncio.create_task(progress.wait())
            done, _ = await asyncio.wait({future, waiter}, timeout=max(0, deadline - asyncio.get_running_loop().time()), return_when=asyncio.FIRST_COMPLETED)
            if future in done:
                waiter.cancel()
                return future.result()
            waiter.cancel()
            if not done:
                raise asyncio.TimeoutError
            progress.clear()
            deadline = asyncio.get_running_loop().time() + timeout_ms / 1000

    async def _handle_connection(self, websocket: Any, _path: str | None = None) -> None:
        try:
            hello = self._decode(await asyncio.wait_for(websocket.recv(), timeout=5))
            if hello.get("type") != "hello" or hello.get("protocol_version") != PROTOCOL_VERSION:
                await self._send(websocket, {"type": "error", "code": "INCOMPATIBLE_PROTOCOL", "message": "不支持的 Extension 协议版本"})
                return
            async with self._connection_lock:
                if self._client is not None:
                    await self._send(websocket, {"type": "error", "code": "EXTENSION_ALREADY_CONNECTED", "message": error_message("EXTENSION_ALREADY_CONNECTED")})
                    return
                self._client = websocket
                await self._send(websocket, {"type": "hello_ack", "protocol_version": PROTOCOL_VERSION})
                self._ready.set()
            async for raw in websocket:
                await self._handle_message(self._decode(raw))
        except (ConnectionClosed, asyncio.TimeoutError, OSError, ValueError, json.JSONDecodeError):
            pass
        finally:
            async with self._connection_lock:
                if self._client is websocket:
                    self._client = None
                    self._ready.clear()
                    self._fail_pending(RPCError(error_message("EXTENSION_NOT_CONNECTED"), "EXTENSION_NOT_CONNECTED"))

    async def _handle_message(self, message: dict[str, Any]) -> None:
        if message.get("type") == "ping" and self._client is not None:
            await self._send(self._client, {"type": "pong"})
            return
        request_id = message.get("id")
        transfer = self._artifact_transfers.get(request_id) if isinstance(request_id, str) else None
        if transfer and message.get("type") in {"artifact_start", "artifact_chunk", "artifact_end"}:
            self._handle_artifact_message(transfer, message)
            return
        if message.get("type") == "progress" and isinstance(request_id, str) and message.get("phase") in PROGRESS_PHASES:
            if request_id in self._progress_events:
                self._progress_events[request_id].set()
            callback = self._callbacks.get(request_id)
            if callback:
                callback(message)
            return
        future = self._pending.get(request_id) if message.get("type") == "response" else None
        if future and not future.done():
            future.set_result(message)

    @staticmethod
    def _handle_artifact_message(transfer: dict[str, Any], message: dict[str, Any]) -> None:
        if transfer.get("error"):
            return
        try:
            message_type = message.get("type")
            if message_type == "artifact_start":
                if transfer.get("expected") is not None or not isinstance(message.get("size"), int) or message["size"] < 0 or message["size"] > MAX_ARTIFACT_BYTES:
                    raise RPCError("Artifact 起始块无效", "ARTIFACT_TRANSFER_FAILED", safe_to_retry=True)
                transfer["expected"] = message["size"]
                transfer["mime_type"] = message.get("mime_type")
                return
            if transfer.get("ended"):
                raise RPCError("Artifact 结束块后仍收到数据", "ARTIFACT_TRANSFER_FAILED", safe_to_retry=True)
            if message_type == "artifact_chunk":
                sequence = message.get("sequence")
                if transfer.get("expected") is None or sequence != transfer.get("next_sequence") or not isinstance(message.get("data"), str):
                    raise RPCError("Artifact 分块顺序无效", "ARTIFACT_TRANSFER_FAILED", safe_to_retry=True)
                chunk = base64.b64decode(message["data"], validate=True)
                if len(transfer["data"]) + len(chunk) > MAX_ARTIFACT_BYTES:
                    raise RPCError("Artifact 超过大小限制", "ARTIFACT_TOO_LARGE", safe_to_retry=True)
                transfer["data"].extend(chunk)
                transfer["next_sequence"] += 1
                return
            if message_type == "artifact_end":
                if transfer.get("expected") != len(transfer["data"]):
                    raise RPCError("Artifact 结束块大小不匹配", "ARTIFACT_TRANSFER_FAILED", safe_to_retry=True)
                transfer["ended"] = True
        except (binascii.Error, ValueError):
            transfer["error"] = RPCError("Artifact 分块编码无效", "ARTIFACT_TRANSFER_FAILED", safe_to_retry=True)
        except RPCError as exc:
            transfer["error"] = exc
        finally:
            if message.get("type") == "artifact_end" or transfer.get("error"):
                done = transfer.get("done")
                if isinstance(done, asyncio.Event):
                    done.set()

    @staticmethod
    def _decode(raw: str | bytes) -> dict[str, Any]:
        message = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        if not isinstance(message, dict):
            raise ValueError("RPC 消息必须是 JSON 对象")
        return message

    @staticmethod
    async def _send(websocket: Any, message: dict[str, Any]) -> None:
        await websocket.send(json.dumps(message, ensure_ascii=False))

    def _fail_pending(self, error: RPCError) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
