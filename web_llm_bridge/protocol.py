"""Extension 和 Broker 共享的协议常量及校验。"""

from __future__ import annotations

from typing import Any, Final
BRIDGE_HOST: Final = "127.0.0.1"
EXTENSION_PORT: Final = 8765
EXTENSION_GRACE_SECONDS: Final = 2.0
EXTENSION_HANDSHAKE_TIMEOUT_SECONDS: Final = 60.0
# 语义别名，供浏览器启动层和上层调用方使用。
BROWSER_START_GRACE_SECONDS: Final = EXTENSION_GRACE_SECONDS
BROWSER_HANDSHAKE_TIMEOUT_SECONDS: Final = EXTENSION_HANDSHAKE_TIMEOUT_SECONDS
BROKER_PORT: Final = 8766
MAX_MESSAGE_BYTES: Final = 8 * 1024 * 1024
PROTOCOL_VERSION: Final = 2
DEFAULT_HISTORY_LIMIT: Final = 5
MAX_HISTORY_LIMIT: Final = 1_000
MAX_DEBUG_TRACE_EVENTS: Final = 128
MAX_DEBUG_TRACE_REQUESTS: Final = 16
PROGRESS_PHASES: Final = {"submitted", "thinking", "working", "tool_call", "streaming"}
ERROR_MESSAGES: Final = {
    "EXTENSION_NOT_CONNECTED": "尚未检测到浏览器扩展",
    "BROWSER_START_FAILED": "浏览器启动失败",
    "BROWSER_NOT_FOUND": "找不到可用的浏览器可执行文件",
    "EXTENSION_HANDSHAKE_TIMEOUT": "等待浏览器扩展握手超时",
    "BROWSER_EXTENSION_NOT_CONNECTED": "浏览器已启动但扩展未连接到 Bridge",
    "BROWSER_LAUNCH_FAILED": "浏览器启动失败",
    "EXTENSION_ALREADY_CONNECTED": "已有浏览器扩展连接到 Bridge",
    "INVALID_ORIGIN": "WebSocket 连接来源不是允许的浏览器扩展",
    "INCOMPATIBLE_PROTOCOL": "浏览器扩展协议版本不兼容",
    "INVALID_URL": "Provider 不支持该 URL",
    "TAB_CLOSED": "绑定的网页标签页已关闭",
    "CHAT_STATE_UNKNOWN": "消息可能已经提交，但当前无法确认页面的最终执行状态",
    "RPC_TIMEOUT": "等待浏览器扩展响应超时",
    "RESPONSE_TIMEOUT": "连续 5 分钟未检测到页面更新，等待回复超时",
    "RESPONSE_TOO_LARGE": "Broker 响应超过协议大小限制",
    "SESSION_NOT_FOUND": "Session 不存在",
    "ARTIFACT_NOT_FOUND": "Artifact 不存在",
    "ARTIFACT_UNAVAILABLE": "Artifact 来源不可用",
    "ARTIFACT_TOO_LARGE": "Artifact 超过大小限制",
    "ARTIFACT_TRANSFER_FAILED": "Artifact 传输失败",
    "ARTIFACT_INVALID_TYPE": "Artifact 类型无效",
    "ARTIFACT_SOURCE_EXPIRED": "Artifact 来源已过期",
    "ARTIFACT_NOT_READY": "Artifact 尚未就绪",
    "ARTIFACT_WRITE_FAILED": "Artifact 文件写入失败",
    "DEBUG_TRACE_NOT_FOUND": "找不到指定的调试 Trace",
    "INTERNAL_ERROR": "Web LLM Bridge 内部错误",
}


def error_message(code: str, fallback: str | None = None) -> str:
    return ERROR_MESSAGES.get(code, fallback or ERROR_MESSAGES["INTERNAL_ERROR"])


def error_response(request_id: Any, code: str, message: str | None = None, *, safe_to_retry: bool = False) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message or error_message(code), "safe_to_retry": safe_to_retry}}
