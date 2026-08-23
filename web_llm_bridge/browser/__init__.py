"""浏览器启动与 Extension 握手基础设施。"""

from .launcher import (
    BROWSER_GRACE_SECONDS,
    HANDSHAKE_TIMEOUT_SECONDS,
    BrowserBootstrap,
    BrowserLauncher,
    launch_browser,
)

__all__ = [
    "BROWSER_GRACE_SECONDS",
    "HANDSHAKE_TIMEOUT_SECONDS",
    "BrowserBootstrap",
    "BrowserLauncher",
    "launch_browser",
]
