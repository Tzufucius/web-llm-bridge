"""启动用户浏览器并等待已安装扩展完成握手。

该模块只负责拉起浏览器进程，不管理进程生命周期、不探测已有进程，
也不会创建临时 profile。浏览器继续使用用户自己的默认 profile。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Sequence

from ..errors import BrowserLaunchError, RPCError
from ..protocol import (
    EXTENSION_GRACE_SECONDS,
    EXTENSION_HANDSHAKE_TIMEOUT_SECONDS,
)
from ..transport.extension import ExtensionTransport

def _find_executable(browser: str) -> str | None:
    """Resolve only known browser names; never scan the whole disk."""
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if browser == "chrome" else ("microsoft-edge", "microsoft-edge-stable", "msedge")
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        candidates = (
            Path(os.environ.get("PROGRAMFILES", "")) / ("Google/Chrome/Application/chrome.exe" if browser == "chrome" else "Microsoft/Edge/Application/msedge.exe"),
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / ("Google/Chrome/Application/chrome.exe" if browser == "chrome" else "Microsoft/Edge/Application/msedge.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / ("Google/Chrome/Application/chrome.exe" if browser == "chrome" else "Microsoft/Edge/Application/msedge.exe"),
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


class BrowserLauncher:
    """使用用户默认浏览器 profile 打开 URL。"""

    def __init__(self, executable: str | os.PathLike[str] | None = None, browser: str | None = None) -> None:
        self.executable = str(executable) if executable is not None else None
        self.browser = browser or os.environ.get("WEB_LLM_BRIDGE_BROWSER", "default").strip() or "default"

    def launch(self, url: str | None = None, *, extra_args: Sequence[str] = ()) -> Any:
        configured = self.executable or self.browser
        if configured == "default" and self.executable is None:
            try:
                if not webbrowser.open(url or "about:blank", new=0, autoraise=True):
                    raise BrowserLaunchError("系统默认浏览器未接受启动请求", "BROWSER_LAUNCH_FAILED")
                return None
            except BrowserLaunchError:
                raise
            except OSError as exc:
                raise BrowserLaunchError("系统默认浏览器启动失败", "BROWSER_LAUNCH_FAILED") from exc
        executable = self.executable or (configured if os.path.isabs(configured) else _find_executable(configured))
        if not executable:
            raise BrowserLaunchError(f"找不到可用的浏览器：{configured}", "BROWSER_LAUNCH_FAILED")
        command = [executable, *extra_args]
        if url:
            command.append(url)
        try:
            return subprocess.Popen(command, close_fds=True)
        except (FileNotFoundError, OSError) as exc:
            raise BrowserLaunchError(f"无法启动浏览器：{executable}", "BROWSER_LAUNCH_FAILED") from exc
class BrowserBootstrap:
    """协调 Extension transport、浏览器启动和握手等待。"""

    def __init__(self, transport: ExtensionTransport, launcher: BrowserLauncher | None = None) -> None:
        self.transport = transport
        self.launcher = launcher or BrowserLauncher()
        self._launch_lock = asyncio.Lock()

    async def start(self, url: str | None = None, *, handshake_timeout: float = EXTENSION_HANDSHAKE_TIMEOUT_SECONDS) -> None:
        await self.transport.start()
        if self.transport.connected:
            return
        if EXTENSION_GRACE_SECONDS > 0:
            try:
                await self.transport.wait_until_ready(EXTENSION_GRACE_SECONDS)
                if self.transport.connected:
                    return
            except RPCError:
                pass
        async with self._launch_lock:
            if self.transport.connected:
                return
            try:
                self.launcher.launch(url or "about:blank")
            except BrowserLaunchError:
                raise
            try:
                await self.transport.wait_until_ready(handshake_timeout)
            except RPCError as exc:
                raise BrowserLaunchError("浏览器已启动但扩展未连接到 Bridge", "BROWSER_EXTENSION_NOT_CONNECTED") from exc

    async def close(self) -> None:
        """关闭 Bridge 监听；不会终止用户浏览器。"""
        await self.transport.close()
