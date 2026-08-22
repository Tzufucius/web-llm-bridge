"""ChatGPT Web Bridge 的手动登录初始化脚本。

安装依赖::

    pip install playwright
    playwright install chromium

脚本不会读取账号、密码、Cookie 或 Token。用户在可见浏览器中完成登录后，
Playwright 会把浏览器 Profile 持久化到本目录的 ``chatgpt_browser_profile``，
供 ``chatgpt_web_bridge.py`` 后续复用。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Final

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


PROFILE_DIR: Final[Path] = Path(__file__).resolve().parent / "chatgpt_browser_profile"
SESSION_METADATA_FILE: Final[Path] = PROFILE_DIR / "session_metadata.json"
LOGIN_URL: Final[str] = "https://chatgpt.com/"
HEADLESS: Final[bool] = False
LOGIN_TIMEOUT_MS: Final[int] = 300_000
PROMPT_SELECTORS: Final[list[str]] = [
    "#prompt-textarea",
    '[contenteditable="true"][role="textbox"]',
]

LOGGER = logging.getLogger("chatgpt_web_login")


class ChatGPTLoginError(RuntimeError):
    """手动登录或 Profile 初始化失败。"""


async def _select_page(context: BrowserContext) -> Page:
    for page in context.pages:
        if page.url in {"", "about:blank"} and not page.is_closed():
            return page
    return await context.new_page()


def _save_metadata(page: Page) -> None:
    metadata = {
        "last_login_at": datetime.now().astimezone().isoformat(),
        "page_url": page.url,
        "profile_dir": str(PROFILE_DIR),
        "note": "此文件不包含密码、Cookie 或 Token；登录态由 Chromium Profile 保存。",
    }
    SESSION_METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


async def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    playwright = await async_playwright().start()
    context: BrowserContext | None = None

    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=HEADLESS,
        )
        page = await _select_page(context)
        LOGGER.info("打开 ChatGPT 登录页面")
        try:
            await page.goto(
                LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=LOGIN_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError as exc:
            raise ChatGPTLoginError("ChatGPT 页面加载超时，请检查网络连接") from exc
        except PlaywrightError as exc:
            raise ChatGPTLoginError("ChatGPT 页面打开失败，请检查网络连接") from exc

        print(f"浏览器 Profile：{PROFILE_DIR}")
        print("请在打开的浏览器中手动完成 ChatGPT 登录。")
        print("脚本不会读取或保存账号、密码、Cookie、Token。")
        print("登录成功后，等待页面显示 ChatGPT 输入框。")

        prompt = page.locator(",".join(PROMPT_SELECTORS)).first
        try:
            await prompt.wait_for(state="visible", timeout=LOGIN_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ChatGPTLoginError(
                "在限定时间内未检测到 ChatGPT 输入框，可能尚未登录或页面结构发生变化"
            ) from exc

        _save_metadata(page)
        LOGGER.info("ChatGPT 登录态已保存")
        print(f"登录态已保存到：{PROFILE_DIR}")
        print(f"状态信息：{SESSION_METADATA_FILE}")
        input("按 Enter 关闭浏览器并结束登录脚本：")
    except ChatGPTLoginError as exc:
        LOGGER.error("%s", exc)
        print(f"错误：{exc}")
    finally:
        if context is not None:
            await context.close()
        await playwright.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已取消登录脚本。")
