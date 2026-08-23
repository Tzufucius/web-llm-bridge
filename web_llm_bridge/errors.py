"""跨进程协议使用的稳定错误类型。"""

from __future__ import annotations


class WebLLMBridgeError(RuntimeError):
    def __init__(self, message: str, code: str = "INTERNAL_ERROR", *, safe_to_retry: bool = False) -> None:
        self.code = code
        self.safe_to_retry = safe_to_retry
        super().__init__(message)


class RPCError(WebLLMBridgeError):
    """Extension 或 Broker 返回的 RPC 错误。"""


class BrowserLaunchError(WebLLMBridgeError):
    """浏览器启动或扩展握手失败。"""


# 迁移期兼容别名；新代码应使用 WebLLMBridgeError。
ChatGPTBridgeError = WebLLMBridgeError
