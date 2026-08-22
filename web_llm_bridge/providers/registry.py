"""Provider 名称到实现的注册表。"""

from __future__ import annotations

from ..errors import WebLLMBridgeError
from .base import ProviderDefinition
from .chatgpt import CHATGPT_PROVIDER


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderDefinition] = {CHATGPT_PROVIDER.id: CHATGPT_PROVIDER}

    def get_provider(self, provider: str) -> ProviderDefinition:
        if provider not in self._providers:
            raise WebLLMBridgeError(f"不支持的 provider：{provider}", "PROVIDER_NOT_FOUND")
        return self._providers[provider]

    def register(self, definition: ProviderDefinition) -> None:
        if definition.id in self._providers:
            raise ValueError(f"Provider 已注册：{definition.id}")
        self._providers[definition.id] = definition

    def all(self) -> tuple[ProviderDefinition, ...]:
        return tuple(self._providers.values())
