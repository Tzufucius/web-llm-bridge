"""启动用户浏览器并等待已安装扩展完成握手。

该模块只负责拉起浏览器进程，不管理进程生命周期、不探测已有进程，
也不会创建临时 profile。浏览器继续使用用户自己的默认 profile。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from ..errors import BrowserLaunchError
from ..protocol import (
    EXTENSION_GRACE_SECONDS,
    EXTENSION_HANDSHAKE_TIMEOUT_SECONDS,
)
from ..transport.extension import ExtensionTransport

BROWSER_GRACE_SECONDS = EXTENSION_GRACE_SECONDS
HANDSHAKE_TIMEOUT_SECONDS = EXTENSION_HANDSHAKE_TIMEOUT_SECONDS


def _default_executable() -> str | None:
    """按 PATH 和常见系统安装路径查找 Chromium 系浏览器。"""
    names = ("chrome", "google-chrome", "chromium", "chromium-browser", "msedge")
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        candidates = (
            Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


class BrowserLauncher:
    """使用用户默认浏览器 profile 打开 URL。"""

    def __init__(self, executable: str | os.PathLike[str] | None = None) -> None:
        self.executable = str(executable) if executable is not None else None

    def launch(self, url: str | None = None, *, extra_args: Sequence[str] = ()) -> subprocess.Popen[bytes]:
        executable = self.executable or _default_executable()
        if not executable:
            raise BrowserLaunchError("找不到可用的浏览器可执行文件", "BROWSER_NOT_FOUND")
        command = [executable, *extra_args]
        if url:
            command.append(url)
        try:
            return subprocess.Popen(command, close_fds=True)
        except (FileNotFoundError, OSError) as exc:
            raise BrowserLaunchError(f"无法启动浏览器：{executable}", "BROWSER_START_FAILED") from exc


def launch_browser(url: str | None = None, *, executable: str | os.PathLike[str] | None = None, extra_args: Sequence[str] = ()) -> subprocess.Popen[bytes]:
    """使用一次性 Launcher 打开 URL。"""
    return BrowserLauncher(executable).launch(url, extra_args=extra_args)


class BrowserBootstrap:
    """协调 Extension transport、浏览器启动和握手等待。"""

    def __init__(self, transport: ExtensionTransport, launcher: BrowserLauncher | None = None) -> None:
        self.transport = transport
        self.launcher = launcher or BrowserLauncher()

    async def start(self, url: str | None = None, *, handshake_timeout: float = HANDSHAKE_TIMEOUT_SECONDS) -> None:
        await self.transport.start()
        if self.transport.connected:
            return
        self.launcher.launch(url)
        await asyncio.sleep(BROWSER_GRACE_SECONDS)
        await self.transport.wait_until_ready(handshake_timeout)

    async def close(self) -> None:
        """关闭 Bridge 监听；不会终止用户浏览器。"""
        await self.transport.close()
