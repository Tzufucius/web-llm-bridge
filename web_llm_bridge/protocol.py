"""Extension 和 Broker 共享的协议常量及校验。"""

from __future__ import annotations

from typing import Any, Final
BRIDGE_HOST: Final = "127.0.0.1"
EXTENSION_PORT: Final = 8765
BROKER_PORT: Final = 8766
MAX_MESSAGE_BYTES: Final = 8 * 1024 * 1024
PROTOCOL_VERSION: Final = 1
DEFAULT_HISTORY_LIMIT: Final = 5
MAX_HISTORY_LIMIT: Final = 1_000
PROGRESS_PHASES: Final = {"submitted", "thinking", "working", "tool_call", "streaming"}
ERROR_MESSAGES: Final = {
    "EXTENSION_NOT_CONNECTED": "尚未检测到浏览器扩展",
    "EXTENSION_ALREADY_CONNECTED": "已有浏览器扩展连接到 Bridge",
    "INVALID_ORIGIN": "WebSocket 连接来源不是允许的浏览器扩展",
    "INCOMPATIBLE_PROTOCOL": "浏览器扩展协议版本不兼容",
    "INVALID_URL": "Provider 不支持该 URL",
    "TAB_CLOSED": "绑定的网页标签页已关闭",
    "CHAT_STATE_UNKNOWN": "消息可能已经提交，但当前无法确认页面的最终执行状态",
    "RPC_TIMEOUT": "等待浏览器扩展响应超时",
    "RESPONSE_TIMEOUT": "连续 5 分钟未检测到页面更新，等待回复超时",
    "RESPONSE_TOO_LARGE": "Broker 响应超过协议大小限制",
    "INTERNAL_ERROR": "Web LLM Bridge 内部错误",
}


def error_message(code: str, fallback: str | None = None) -> str:
    return ERROR_MESSAGES.get(code, fallback or ERROR_MESSAGES["INTERNAL_ERROR"])


def error_response(request_id: Any, code: str, message: str | None = None, *, safe_to_retry: bool = False) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message or error_message(code), "safe_to_retry": safe_to_retry}}
