"""无运行时状态的 Provider 定义。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlparse

from ..errors import WebLLMBridgeError
from ..protocol import error_message


@dataclass(frozen=True)
class ProviderDefinition:
    """浏览器 Provider 的不可变静态元数据。"""

    id: str
    default_url: str
    hosts: frozenset[str]
    capabilities: Mapping[str, bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "hosts", frozenset(self.hosts))
        object.__setattr__(self, "capabilities", MappingProxyType(dict(self.capabilities)))

    def normalize_url(self, url: str) -> str:
        if not isinstance(url, str):
            raise WebLLMBridgeError("url 参数必须是字符串", "INVALID_ARGUMENT")
        parsed = urlparse(url.strip())
        if parsed.scheme != "https" or parsed.hostname not in self.hosts:
            raise WebLLMBridgeError(error_message("INVALID_URL"), "INVALID_URL")
        path = (parsed.path or "/").rstrip("/") or "/"
        return f"https://{parsed.hostname.lower()}{path}"
