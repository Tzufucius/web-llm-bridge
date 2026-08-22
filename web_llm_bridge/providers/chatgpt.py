"""ChatGPT 的静态 Provider 定义。"""

from __future__ import annotations

from .base import ProviderDefinition


CHATGPT_PROVIDER = ProviderDefinition(
    id="chatgpt",
    default_url="https://chatgpt.com/",
    hosts=frozenset({"chatgpt.com", "www.chatgpt.com"}),
    capabilities={
        "chat": True,
        "getMessages": True,
        "history": True,
        "fullHistory": True,
        "markdown": True,
        "latex": True,
        "persistentConversation": True,
    },
)
