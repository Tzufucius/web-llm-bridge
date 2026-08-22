"""Python 与 ChatGPT Web Extension 之间的 Bridge Core。

Broker 是 Extension WebSocket 的唯一进程所有者。这个模块保留现有
``ChatGPTSession`` 的兼容导出，供 Broker 和测试使用；交互式 CLI 位于
``chatgpt_web_bridge.py`` / ``chatgpt_agent_cli.py``。
"""

from __future__ import annotations

try:
    from .chatgpt_web_bridge import (  # type: ignore
        ALLOWED_HOSTS,
        BRIDGE_HOST,
        BRIDGE_PORT,
        DEFAULT_HISTORY_LIMIT,
        ERROR_MESSAGES,
        EXTENSION_CONNECT_TIMEOUT_MS,
        HISTORY_RPC_TIMEOUT_MS,
        MAX_HISTORY_LIMIT,
        MAX_WS_MESSAGE_SIZE,
        PROGRESS_PHASES,
        RESPONSE_IDLE_TIMEOUT_MS,
        ChatGPTBridgeError,
        ChatGPTSession,
        _BridgeRPCError,
        _BridgeTransport,
    )
except ImportError:  # direct script-directory imports
    from chatgpt_web_bridge import (  # type: ignore
        ALLOWED_HOSTS,
        BRIDGE_HOST,
        BRIDGE_PORT,
        DEFAULT_HISTORY_LIMIT,
        ERROR_MESSAGES,
        EXTENSION_CONNECT_TIMEOUT_MS,
        HISTORY_RPC_TIMEOUT_MS,
        MAX_HISTORY_LIMIT,
        MAX_WS_MESSAGE_SIZE,
        PROGRESS_PHASES,
        RESPONSE_IDLE_TIMEOUT_MS,
        ChatGPTBridgeError,
        ChatGPTSession,
        _BridgeRPCError,
        _BridgeTransport,
    )

from urllib.parse import urlparse


def normalize_conversation_url(url: str) -> str:
    """按 origin + pathname 规范化 URL，忽略 query 和 fragment。"""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ChatGPTBridgeError("仅支持 https://chatgpt.com 或 https://www.chatgpt.com", "INVALID_URL")
    hostname = parsed.hostname.lower()
    origin = f"{parsed.scheme}://{hostname}"
    pathname = parsed.path or "/"
    if not pathname.startswith("/"):
        pathname = "/" + pathname
    if pathname != "/":
        pathname = pathname.rstrip("/")
    return origin + pathname


__all__ = [
    "ALLOWED_HOSTS",
    "BRIDGE_HOST",
    "BRIDGE_PORT",
    "ChatGPTBridgeError",
    "ChatGPTSession",
    "DEFAULT_HISTORY_LIMIT",
    "ERROR_MESSAGES",
    "EXTENSION_CONNECT_TIMEOUT_MS",
    "HISTORY_RPC_TIMEOUT_MS",
    "MAX_HISTORY_LIMIT",
    "MAX_WS_MESSAGE_SIZE",
    "PROGRESS_PHASES",
    "RESPONSE_IDLE_TIMEOUT_MS",
    "_BridgeRPCError",
    "_BridgeTransport",
    "normalize_conversation_url",
]
