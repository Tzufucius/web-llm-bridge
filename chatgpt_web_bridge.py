"""通过浏览器扩展桥接 ChatGPT Web 的最小 Python Bridge。

安装依赖::

    python -m pip install -r tools/chatgpt_web_bridge/requirements.txt

Python 只负责 localhost WebSocket RPC、Session 和 CLI；ChatGPT DOM 由
``extension/content.js`` 负责。浏览器登录状态完全由用户正常使用的
Chrome/Edge 管理，本程序不会读取或保存密码、Cookie、Token，也不会启动浏览器。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Final
from urllib.parse import urlparse
from uuid import uuid4

import websockets

try:
    from websockets.asyncio.server import serve
except ImportError:  # websockets 旧版本兼容
    from websockets import serve

from websockets.exceptions import ConnectionClosed


# =========================
# Configuration
# =========================

BRIDGE_HOST: Final[str] = "127.0.0.1"
BRIDGE_PORT: Final[int] = 8765
PROTOCOL_VERSION: Final[int] = 1
EXTENSION_CONNECT_TIMEOUT_MS: Final[int] = 30_000
RPC_TIMEOUT_MS: Final[int] = 30_000
RESPONSE_TIMEOUT_MS: Final[int] = 180_000
HISTORY_RPC_TIMEOUT_MS: Final[int] = 70_000
MAX_WS_MESSAGE_SIZE: Final[int] = 8 * 1024 * 1024
MIN_WEBSOCKETS_VERSION: Final[tuple[int, int]] = (14, 0)
DEFAULT_HISTORY_LIMIT: Final[int] = 5
MAX_HISTORY_LIMIT: Final[int] = 1_000
ALLOWED_HOSTS: Final[set[str]] = {"chatgpt.com", "www.chatgpt.com"}
ALLOWED_EXTENSION_ORIGIN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^chrome-extension://[a-p]{32}$"
)

LOGGER = logging.getLogger("chatgpt_web_bridge")


# =========================
# Errors
# =========================


ERROR_MESSAGES: Final[dict[str, str]] = {
    "EXTENSION_NOT_CONNECTED": "尚未检测到 ChatGPT Web Bridge 浏览器扩展",
    "EXTENSION_ALREADY_CONNECTED": "已有浏览器扩展连接到 Bridge",
    "INVALID_ORIGIN": "WebSocket 连接来源不是允许的浏览器扩展",
    "INCOMPATIBLE_PROTOCOL": "浏览器扩展协议版本不兼容",
    "INVALID_URL": "仅支持 https://chatgpt.com 或 https://www.chatgpt.com",
    "PAGE_NOT_READY": "ChatGPT 页面尚未准备完成",
    "TAB_CLOSED": "绑定的 ChatGPT 标签页已关闭",
    "CONTENT_SCRIPT_UNAVAILABLE": "ChatGPT 内容脚本不可用",
    "PROMPT_NOT_FOUND": "未找到 ChatGPT 输入框",
    "INPUT_FAILED": "文本未成功写入 ChatGPT 输入框",
    "SEND_FAILED": "消息点击发送后未确认提交成功",
    "SEND_BUTTON_NOT_FOUND": "未找到可靠的 ChatGPT 发送按钮",
    "BUSY": "ChatGPT 当前仍在生成回复",
    "RESPONSE_TIMEOUT": "等待 ChatGPT 回复超时",
    "DOM_CHANGED": "ChatGPT 页面结构可能已经发生变化",
    "INTERNAL_ERROR": "ChatGPT Web Bridge 内部错误",
    "RPC_TIMEOUT": "等待浏览器扩展响应超时",
    "DEPENDENCY_VERSION": "websockets 版本过低，请升级到 14.0 或更高版本",
}


class ChatGPTBridgeError(RuntimeError):
    """ChatGPT Web Bridge 操作失败。"""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR") -> None:
        self.code = code
        super().__init__(message)


class _BridgeRPCError(RuntimeError):
    """Extension 返回的内部 RPC 错误。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _error_message(code: str, fallback: str | None = None) -> str:
    return ERROR_MESSAGES.get(code, fallback or ERROR_MESSAGES["INTERNAL_ERROR"])


# =========================
# WebSocket Transport
# =========================


def _validate_websockets_version() -> None:
    version_text = str(getattr(websockets, "__version__", "unknown"))
    try:
        major, minor = (int(part) for part in version_text.split(".")[:2])
    except (TypeError, ValueError) as exc:
        raise ChatGPTBridgeError(
            f"{_error_message('DEPENDENCY_VERSION')} 当前版本：{version_text}",
            "DEPENDENCY_VERSION",
        ) from exc
    if (major, minor) < MIN_WEBSOCKETS_VERSION:
        raise ChatGPTBridgeError(
            f"{_error_message('DEPENDENCY_VERSION')} 当前版本：{version_text}",
            "DEPENDENCY_VERSION",
        )


class _BridgeTransport:
    """单个 Extension WebSocket client 的 JSON RPC transport。"""

    def __init__(self) -> None:
        self._server: Any | None = None
        self._client: Any | None = None
        self._connection_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._client_ready = asyncio.Event()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._closed = False

    async def start(self) -> None:
        if self._server is not None:
            return
        _validate_websockets_version()
        try:
            self._server = await serve(
                self._handle_connection,
                BRIDGE_HOST,
                BRIDGE_PORT,
                ping_interval=None,
                max_size=MAX_WS_MESSAGE_SIZE,
                origins=[ALLOWED_EXTENSION_ORIGIN_PATTERN],
            )
        except OSError as exc:
            raise ChatGPTBridgeError(
                f"无法监听 {BRIDGE_HOST}:{BRIDGE_PORT}，可能已有 Bridge 正在运行",
                "INTERNAL_ERROR",
            ) from exc
        LOGGER.info("WebSocket Bridge 已监听 ws://%s:%s", BRIDGE_HOST, BRIDGE_PORT)

    async def wait_extension(self, timeout_ms: int = EXTENSION_CONNECT_TIMEOUT_MS) -> None:
        if self._closed:
            raise _BridgeRPCError("EXTENSION_NOT_CONNECTED", "Bridge 已关闭")
        if self._client_ready.is_set():
            return
        try:
            await asyncio.wait_for(
                self._client_ready.wait(),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError as exc:
            raise _BridgeRPCError(
                "EXTENSION_NOT_CONNECTED",
                _error_message("EXTENSION_NOT_CONNECTED"),
            ) from exc

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        timeout_ms: int = RPC_TIMEOUT_MS,
    ) -> dict[str, Any]:
        await self.wait_extension()
        request_id = str(uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        request = {
            "type": "request",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            async with self._send_lock:
                client = self._client
                if client is None:
                    raise _BridgeRPCError(
                        "EXTENSION_NOT_CONNECTED",
                        _error_message("EXTENSION_NOT_CONNECTED"),
                    )
                await client.send(json.dumps(request, ensure_ascii=False))

            response = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError as exc:
            raise _BridgeRPCError("RPC_TIMEOUT", _error_message("RPC_TIMEOUT")) from exc
        except _BridgeRPCError:
            raise
        except (ConnectionClosed, OSError) as exc:
            raise _BridgeRPCError(
                "EXTENSION_NOT_CONNECTED",
                _error_message("EXTENSION_NOT_CONNECTED"),
            ) from exc
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()

        if response.get("type") != "response" or response.get("id") != request_id:
            raise _BridgeRPCError("INTERNAL_ERROR", "Extension 返回了无效 RPC 响应")
        if response.get("ok") is not True:
            error = response.get("error")
            if not isinstance(error, dict):
                raise _BridgeRPCError("INTERNAL_ERROR", "Extension 返回了无效错误")
            code = str(error.get("code", "INTERNAL_ERROR"))
            message = str(error.get("message", _error_message(code)))
            raise _BridgeRPCError(code, message)

        result = response.get("result", {})
        if not isinstance(result, dict):
            raise _BridgeRPCError("INTERNAL_ERROR", "Extension 返回了无效结果")
        return result

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._client_ready.clear()
        self._fail_pending(
            _BridgeRPCError("EXTENSION_NOT_CONNECTED", "Bridge 已关闭")
        )

        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.close()
            except (ConnectionClosed, OSError):
                pass

        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()
        LOGGER.info("WebSocket Bridge 已关闭")

    async def _handle_connection(self, websocket: Any, _path: str | None = None) -> None:
        try:
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=5)
            hello = self._decode_message(raw_message)
            if (
                hello.get("type") != "hello"
                or hello.get("protocol_version") != PROTOCOL_VERSION
            ):
                await self._send_json(
                    websocket,
                    {
                        "type": "error",
                        "code": "INCOMPATIBLE_PROTOCOL",
                        "message": "不支持的 Extension 协议版本",
                    },
                )
                await websocket.close()
                return

            async with self._connection_lock:
                if self._client is not None:
                    await self._send_json(
                        websocket,
                        {
                            "type": "error",
                            "code": "EXTENSION_ALREADY_CONNECTED",
                            "message": _error_message("EXTENSION_ALREADY_CONNECTED"),
                        },
                    )
                    await websocket.close()
                    return
                self._client = websocket
                await self._send_json(
                    websocket,
                    {
                        "type": "hello_ack",
                        "protocol_version": PROTOCOL_VERSION,
                    },
                )
                self._client_ready.set()
            LOGGER.info("Extension handshake completed")

            async for raw_message in websocket:
                await self._handle_message(self._decode_message(raw_message))
        except (ConnectionClosed, asyncio.TimeoutError, OSError, ValueError) as exc:
            LOGGER.debug("Extension 连接结束：%s", exc)
        finally:
            async with self._connection_lock:
                if self._client is websocket:
                    self._client = None
                    self._client_ready.clear()
                    self._fail_pending(
                        _BridgeRPCError(
                            "EXTENSION_NOT_CONNECTED",
                            _error_message("EXTENSION_NOT_CONNECTED"),
                        )
                    )
                    LOGGER.warning("浏览器扩展连接已断开")

    async def _handle_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "ping":
            if self._client is not None:
                await self._send_json(self._client, {"type": "pong"})
            return
        if message_type != "response":
            return

        request_id = message.get("id")
        if not isinstance(request_id, str):
            return
        future = self._pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(message)

    @staticmethod
    def _decode_message(raw_message: str | bytes) -> dict[str, Any]:
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")
        message = json.loads(raw_message)
        if not isinstance(message, dict):
            raise ValueError("RPC 消息必须是 JSON 对象")
        return message

    @staticmethod
    async def _send_json(websocket: Any, message: dict[str, Any]) -> None:
        await websocket.send(json.dumps(message, ensure_ascii=False))

    def _fail_pending(self, error: _BridgeRPCError) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(_BridgeRPCError(error.code, error.message))
        self._pending.clear()


# A single localhost server is shared by multiple sessions. Each session still
# owns a different tab_id, so closing one session doesn't close other tabs.
_TRANSPORT_LOCK = asyncio.Lock()
_SHARED_TRANSPORT: _BridgeTransport | None = None
_SHARED_TRANSPORT_USERS = 0


async def _acquire_shared_transport() -> _BridgeTransport:
    global _SHARED_TRANSPORT, _SHARED_TRANSPORT_USERS
    async with _TRANSPORT_LOCK:
        if _SHARED_TRANSPORT is None:
            _SHARED_TRANSPORT = _BridgeTransport()
            try:
                await _SHARED_TRANSPORT.start()
            except Exception:
                _SHARED_TRANSPORT = None
                raise
        _SHARED_TRANSPORT_USERS += 1
        return _SHARED_TRANSPORT


async def _release_shared_transport(transport: _BridgeTransport) -> None:
    global _SHARED_TRANSPORT, _SHARED_TRANSPORT_USERS
    async with _TRANSPORT_LOCK:
        if _SHARED_TRANSPORT is not transport:
            return
        _SHARED_TRANSPORT_USERS = max(0, _SHARED_TRANSPORT_USERS - 1)
        if _SHARED_TRANSPORT_USERS == 0:
            _SHARED_TRANSPORT = None
            await transport.close()


# =========================
# ChatGPT Session
# =========================


class ChatGPTSession:
    """绑定浏览器 Extension 创建的单个 ChatGPT tab。"""

    def __init__(
        self,
        transport: _BridgeTransport,
        tab_id: int,
        current_url: str,
        reopen_on_closed: bool = False,
    ) -> None:
        self._transport = transport
        self._tab_id = tab_id
        self._current_url = current_url
        self._reopen_on_closed = reopen_on_closed
        self._last_history_truncated = False
        self._chat_lock = asyncio.Lock()
        self._closed = False

    @classmethod
    async def open(
        cls,
        url: str,
        reopen_on_closed: bool = False,
    ) -> "ChatGPTSession":
        normalized_url = cls._validate_url(url)
        transport = await _acquire_shared_transport()
        try:
            result = await transport.request(
                "open",
                {"url": normalized_url},
                timeout_ms=EXTENSION_CONNECT_TIMEOUT_MS,
            )
            tab_id = result.get("tab_id")
            if not isinstance(tab_id, int):
                raise ChatGPTBridgeError(
                    "Extension 未返回有效的 tabId",
                    "INTERNAL_ERROR",
                )
            current_url = result.get("url")
            if not isinstance(current_url, str):
                current_url = normalized_url
            LOGGER.info("已绑定 ChatGPT tabId=%s", tab_id)
            return cls(transport, tab_id, current_url, reopen_on_closed)
        except _BridgeRPCError as exc:
            await _release_shared_transport(transport)
            raise ChatGPTBridgeError(
                _error_message(exc.code, exc.message),
                exc.code,
            ) from exc
        except ChatGPTBridgeError:
            await _release_shared_transport(transport)
            raise
        except Exception:
            await _release_shared_transport(transport)
            raise

    async def get_messages(
        self,
        limit: int | None = None,
        full: bool = False,
    ) -> list[dict[str, str]]:
        self._ensure_open()
        self._validate_history_options(limit, full)

        def request_params() -> dict[str, Any]:
            return {"tab_id": self._tab_id, "limit": limit, "full": full}

        try:
            result = await self._request(
                "get_messages",
                request_params(),
                timeout_ms=HISTORY_RPC_TIMEOUT_MS,
            )
        except ChatGPTBridgeError as exc:
            if exc.code != "TAB_CLOSED" or not self._reopen_on_closed:
                raise
            await self._reopen_current_tab()
            result = await self._request(
                "get_messages",
                request_params(),
                timeout_ms=HISTORY_RPC_TIMEOUT_MS,
            )
        messages = result.get("messages")
        if not isinstance(messages, list):
            raise ChatGPTBridgeError("Extension 返回了无效消息列表", "INTERNAL_ERROR")
        for message in messages:
            if (
                not isinstance(message, dict)
                or message.get("role") not in {"user", "assistant"}
                or not isinstance(message.get("content"), str)
            ):
                raise ChatGPTBridgeError("Extension 返回了无效消息", "INTERNAL_ERROR")
        self._last_history_truncated = result.get("truncated") is True
        if self._last_history_truncated:
            LOGGER.warning(
                "历史消息加载达到时间限制，仅返回已捕获的 %s 条消息",
                len(messages),
            )
        self._update_url(result)
        return messages

    async def chat(self, text: str) -> str:
        if not text.strip():
            raise ChatGPTBridgeError("消息不能为空", "INPUT_FAILED")
        async with self._chat_lock:
            self._ensure_open()
            result = await self._request(
                "chat",
                {"tab_id": self._tab_id, "text": text},
                timeout_ms=RESPONSE_TIMEOUT_MS,
            )
            answer = result.get("text")
            if not isinstance(answer, str) or not answer.strip():
                raise ChatGPTBridgeError("Extension 返回了空回复", "INTERNAL_ERROR")
            self._update_url(result)
            LOGGER.info("ChatGPT 回复生成完成，tabId=%s", self._tab_id)
            return answer

    async def __aenter__(self) -> "ChatGPTSession":
        self._ensure_open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._shutdown()

    async def _request(
        self,
        method: str,
        params: dict[str, Any],
        timeout_ms: int = RPC_TIMEOUT_MS,
    ) -> dict[str, Any]:
        try:
            return await self._transport.request(method, params, timeout_ms)
        except _BridgeRPCError as exc:
            code = exc.code
            if method == "chat" and code == "RPC_TIMEOUT":
                code = "RESPONSE_TIMEOUT"
            raise ChatGPTBridgeError(_error_message(code, exc.message), code) from exc

    async def _reopen_current_tab(self) -> None:
        self._ensure_open()
        result = await self._request(
            "open",
            {"url": self._current_url},
            timeout_ms=EXTENSION_CONNECT_TIMEOUT_MS,
        )
        tab_id = result.get("tab_id")
        if not isinstance(tab_id, int):
            raise ChatGPTBridgeError("Extension 未返回有效的 tabId", "INTERNAL_ERROR")
        self._tab_id = tab_id
        self._update_url(result)
        LOGGER.info("已重新绑定 ChatGPT tabId=%s", tab_id)

    @staticmethod
    def _validate_history_options(limit: int | None, full: bool) -> None:
        if not isinstance(full, bool):
            raise ChatGPTBridgeError("full 参数必须是布尔值", "INPUT_FAILED")
        if full:
            return
        if limit is None:
            return
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_HISTORY_LIMIT
        ):
            raise ChatGPTBridgeError(
                f"历史消息数量必须是 1 到 {MAX_HISTORY_LIMIT} 的正整数",
                "INPUT_FAILED",
            )

    def _update_url(self, result: dict[str, Any]) -> None:
        current_url = result.get("url")
        if isinstance(current_url, str) and current_url:
            self._current_url = current_url

    def _ensure_open(self) -> None:
        if self._closed:
            raise ChatGPTBridgeError("当前 ChatGPT Session 已关闭", "INTERNAL_ERROR")

    @staticmethod
    def _validate_url(url: str) -> str:
        normalized_url = url.strip()
        parsed = urlparse(normalized_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ChatGPTBridgeError(
                _error_message("INVALID_URL"),
                "INVALID_URL",
            )
        return normalized_url

    async def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        await _release_shared_transport(self._transport)


# =========================
# CLI
# =========================


async def _ainput(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


def _is_home_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.path in {"", "/"} and not parsed.query and not parsed.fragment


async def _prompt_start_mode() -> bool:
    while True:
        choice = (
            await _ainput(
                "请选择会话启动方式：\n\n"
                "[1] 新建 ChatGPT 对话\n"
                "[2] 打开已有 ChatGPT 对话 URL\n\n"
                "> "
            )
        ).strip().lower()
        if choice in {"", "1"}:
            return False
        if choice == "2":
            return True
        print("请输入 1 或 2。")


async def _prompt_yes_no(prompt: str) -> bool:
    while True:
        answer = (await _ainput(prompt)).strip().lower()
        if answer in {"", "y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("请输入 y/yes 或 n/no。")


async def _prompt_history_options() -> tuple[int | None, bool]:
    while True:
        choice = (
            await _ainput(
                "加载多少条历史消息？\n\n"
                "[Enter] 最近 5 条\n"
                "[n]     自定义条数\n"
                "[a]     全部历史\n\n"
                "> "
            )
        ).strip().lower()
        if not choice:
            return DEFAULT_HISTORY_LIMIT, False
        if choice in {"a", "all"}:
            return None, True
        if choice == "n":
            while True:
                custom = (await _ainput("请输入要加载的历史消息数量：\n> ")).strip()
                if custom.isdigit():
                    value = int(custom)
                    if 1 <= value <= MAX_HISTORY_LIMIT:
                        return value, False
                print(f"请输入 1 到 {MAX_HISTORY_LIMIT} 的正整数。")
        elif choice.isdigit():
            value = int(choice)
            if 1 <= value <= MAX_HISTORY_LIMIT:
                return value, False
            print(f"请输入 1 到 {MAX_HISTORY_LIMIT} 的正整数。")
        else:
            print("请输入数字、n 或 a/all。")


async def _prompt_reopen(session: ChatGPTSession) -> bool:
    print("当前绑定的 ChatGPT 标签页已关闭。")
    print(f"原会话：{session._current_url}")
    if not await _prompt_yes_no("是否重新打开该会话？ [Y/n]\n> "):
        return False
    await session._reopen_current_tab()
    print(f"会话已重新绑定，当前 URL：{session._current_url}")
    return True


async def _load_history_for_cli(
    session: ChatGPTSession,
    limit: int | None = None,
    full: bool = False,
) -> list[dict[str, str]]:
    try:
        return await session.get_messages(limit=limit, full=full)
    except ChatGPTBridgeError as exc:
        if exc.code != "TAB_CLOSED" or not await _prompt_reopen(session):
            raise
        return await session.get_messages(limit=limit, full=full)


def _parse_history_command(command: str) -> tuple[int | None, bool]:
    parts = command.split(maxsplit=1)
    if len(parts) == 1:
        return None, False
    value = parts[1].strip().lower()
    if value in {"all", "a"}:
        return None, True
    if value.isdigit():
        limit = int(value)
        if 1 <= limit <= MAX_HISTORY_LIMIT:
            return limit, False
    raise ChatGPTBridgeError(
        f"/history 数量必须是 1 到 {MAX_HISTORY_LIMIT} 的正整数，或 all",
        "INPUT_FAILED",
    )


def _print_history(messages: list[dict[str, str]]) -> None:
    for message in messages:
        print(f"[{message['role']}]")
        print(message["content"])
        print()


async def main() -> None:
    session: ChatGPTSession | None = None
    try:
        open_existing = await _prompt_start_mode()
        load_history = False
        history_limit: int | None = None
        load_all_history = False
        if open_existing:
            url = (await _ainput("请输入 ChatGPT Conversation URL：\n> ")).strip()
            if not url:
                raise ChatGPTBridgeError("URL 不能为空", "INVALID_URL")
            if _is_home_url(url):
                print("该 URL 是 ChatGPT 首页，将按新对话处理。")
            else:
                load_history = await _prompt_yes_no(
                    "是否加载已有对话记录？ [Y/n]\n> "
                )
                if load_history:
                    history_limit, load_all_history = await _prompt_history_options()
        else:
            url = "https://chatgpt.com/"

        print("正在启动 localhost Bridge 并等待浏览器扩展...")
        session = await ChatGPTSession.open(url)
        print("ChatGPT 标签页已绑定。")
        print(f"当前 URL: {session._current_url}")
        if load_history:
            if load_all_history:
                print("正在加载完整历史记录...")
            else:
                print(f"正在加载最近 {history_limit} 条历史消息...")
            messages = await _load_history_for_cli(
                session,
                limit=history_limit,
                full=load_all_history,
            )
            print(f"已加载 {len(messages)} 条历史消息。")
            if session._last_history_truncated:
                print("历史加载达到时间限制，可能仍有更早记录未加载。")
        print("提示：如需连接或重连扩展，请点击浏览器工具栏中的扩展图标。")

        while True:
            try:
                command = (await _ainput("你 > ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if command in {"/exit", "/quit"}:
                break
            if command == "/history" or command.startswith("/history "):
                try:
                    history_limit, load_all_history = _parse_history_command(command)
                    messages = await _load_history_for_cli(
                        session,
                        limit=history_limit,
                        full=load_all_history,
                    )
                    _print_history(messages)
                except ChatGPTBridgeError as exc:
                    LOGGER.error("%s", exc)
                    print(f"错误：{exc}")
                continue
            if not command:
                continue

            try:
                answer = await session.chat(command)
                print(f"ChatGPT > {answer}")
            except ChatGPTBridgeError as exc:
                LOGGER.error("%s", exc)
                print(f"错误：{exc}")
                if exc.code == "TAB_CLOSED":
                    try:
                        await _prompt_reopen(session)
                    except ChatGPTBridgeError as reopen_error:
                        LOGGER.error("%s", reopen_error)
                        print(f"错误：{reopen_error}")
    except (ChatGPTBridgeError, EOFError, KeyboardInterrupt) as exc:
        if isinstance(exc, ChatGPTBridgeError):
            LOGGER.error("%s", exc)
            print(f"错误：{exc}")
    finally:
        if session is not None:
            await session._shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main())
