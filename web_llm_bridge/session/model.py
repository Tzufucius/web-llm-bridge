"""公共的 Broker-backed WebLLMSession 句柄。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..client import rpc_call


@dataclass
class WebLLMSession:
    """轻量句柄；不直接监听 :8765，所有操作通过本机 Broker :8766。"""
    provider: str = "chatgpt"
    session_id: str | None = None
    conversation_url: str | None = None
    reopen_on_closed: bool = False

    @classmethod
    async def open(cls, *, provider: str = "chatgpt", new: bool = False, url: str | None = None, session_id: str | None = None, reopen_on_closed: bool | None = None) -> "WebLLMSession":
        result = await rpc_call("open", {"provider": provider, "new": new, "url": url, "session_id": session_id, "reopen_on_closed": reopen_on_closed})
        return cls(provider=result["provider"], session_id=result["session_id"], conversation_url=result.get("conversation_url"), reopen_on_closed=result.get("reopen_on_closed", False))

    async def chat(self, text: str, *, progress: Callable[[dict[str, Any]], None] | None = None) -> str:
        result = await rpc_call("chat", {"provider": self.provider, "session_id": self.session_id, "text": text}, progress=progress)
        self._update(result)
        return result["text"]

    async def get_messages(self, *, limit: int | None = None, full: bool = False) -> list[dict[str, str]]:
        result = await rpc_call("get_messages", {"provider": self.provider, "session_id": self.session_id, "limit": limit, "full": full})
        self._update(result)
        return result["messages"]

    async def __aenter__(self) -> "WebLLMSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        # 句柄不拥有 Broker；退出上下文不会关闭其他客户端正在使用的服务。
        return None

    def _update(self, result: dict[str, Any]) -> None:
        self.session_id = result.get("session_id", self.session_id)
        self.conversation_url = result.get("conversation_url", self.conversation_url)
        self.reopen_on_closed = result.get("reopen_on_closed", self.reopen_on_closed)
