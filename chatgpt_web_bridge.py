"""通过 Playwright 操作 ChatGPT 网页的最小 Web Bridge。

安装依赖::

    pip install playwright
    playwright install chromium

本工具只通过 ChatGPT 网页 DOM 工作，不调用 OpenAI API、ChatGPT 私有接口，
也不抓取网络请求。持久化浏览器 Profile 位于本文件同目录下的
``chatgpt_browser_profile``，首次运行时需要在可见浏览器中手动登录。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


# =========================
# Configuration
# =========================

PROFILE_DIR: Final[Path] = Path(__file__).resolve().parent / "chatgpt_browser_profile"
HEADLESS: Final[bool] = False
BROWSER_CHANNEL: Final[str | None] = None
PAGE_LOAD_TIMEOUT_MS: Final[int] = 60_000
RESPONSE_TIMEOUT_MS: Final[int] = 180_000
STABLE_TIME_MS: Final[int] = 1_000
POLL_INTERVAL_MS: Final[int] = 200

PROMPT_SELECTORS: Final[list[str]] = [
    "#prompt-textarea",
    '[contenteditable="true"][role="textbox"]',
]
SEND_BUTTON_SELECTORS: Final[list[str]] = [
    "#composer-submit-button",
    '[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
]
STOP_BUTTON_SELECTORS: Final[list[str]] = [
    '[data-testid="stop-button"]',
    'button[aria-label*="Stop"]',
]
MESSAGE_SELECTOR: Final[str] = "[data-message-author-role]"
ASSISTANT_SELECTOR: Final[str] = '[data-message-author-role="assistant"]'
ALLOWED_HOSTS: Final[set[str]] = {"chatgpt.com", "www.chatgpt.com"}

LOGGER = logging.getLogger("chatgpt_web_bridge")


# =========================
# Exceptions
# =========================


class ChatGPTBridgeError(RuntimeError):
    """ChatGPT 页面交互失败。"""


# =========================
# ChatGPT Session
# =========================


class ChatGPTSession:
    """绑定一个固定 Playwright Page 的 ChatGPT 会话。"""

    def __init__(
        self,
        playwright: Playwright,
        context: BrowserContext,
        page: Page,
    ) -> None:
        self._playwright = playwright
        self._context = context
        self.page = page
        self._chat_lock = asyncio.Lock()
        self._closed = False

    @classmethod
    async def open(cls, url: str) -> "ChatGPTSession":
        """启动持久化浏览器并绑定指定 ChatGPT 页面。"""

        normalized_url = cls._validate_url(url)
        playwright = await async_playwright().start()
        context: BrowserContext | None = None

        try:
            launch_kwargs: dict[str, object] = {
                "user_data_dir": str(PROFILE_DIR),
                "headless": HEADLESS,
            }
            if BROWSER_CHANNEL is not None:
                launch_kwargs["channel"] = BROWSER_CHANNEL

            context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
            context.set_default_timeout(PAGE_LOAD_TIMEOUT_MS)

            page = await cls._select_page(context)
            session = cls(playwright, context, page)
            LOGGER.info("打开 ChatGPT 页面")
            try:
                await page.goto(
                    normalized_url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_LOAD_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError as exc:
                raise ChatGPTBridgeError("ChatGPT 页面加载失败，请检查网络连接") from exc
            except PlaywrightError as exc:
                raise ChatGPTBridgeError("ChatGPT 页面加载失败，请检查 URL 和网络连接") from exc

            await session._wait_page_ready()
            LOGGER.info("已绑定 ChatGPT 标签页")
            return session
        except ChatGPTBridgeError:
            # 保留 headed 浏览器窗口，方便用户完成登录或检查页面状态。
            raise
        except PlaywrightError as exc:
            if context is not None:
                await context.close()
            await playwright.stop()
            raise ChatGPTBridgeError("无法启动 Playwright 浏览器") from exc
        except Exception:
            if context is not None:
                await context.close()
            await playwright.stop()
            raise

    @staticmethod
    async def _select_page(context: BrowserContext) -> Page:
        """复用空白页，否则新建一个页，避免不必要的多标签页。"""

        for page in context.pages:
            if page.url in {"", "about:blank"} and not page.is_closed():
                return page
        return await context.new_page()

    @staticmethod
    def _validate_url(url: str) -> str:
        normalized_url = url.strip()
        parsed = urlparse(normalized_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError("仅支持 https://chatgpt.com 或 https://www.chatgpt.com")
        return normalized_url

    async def get_messages(self) -> list[dict[str, str]]:
        """读取当前 DOM 中已经加载的用户和 Assistant 消息。"""

        self._ensure_page_open()
        nodes = self.page.locator(MESSAGE_SELECTOR)
        messages: list[dict[str, str]] = []
        try:
            count = await nodes.count()
            for index in range(count):
                node = nodes.nth(index)
                role = await node.get_attribute("data-message-author-role")
                if role not in {"user", "assistant"}:
                    continue
                content = (await node.inner_text()).strip()
                if content:
                    messages.append({"role": role, "content": content})
        except PlaywrightError as exc:
            raise ChatGPTBridgeError(
                "读取 ChatGPT 消息失败，可能由于页面结构发生变化"
            ) from exc
        return messages

    async def chat(self, text: str) -> str:
        """发送一条文本消息，并返回最后一条完整 Assistant 回复。"""

        if not text.strip():
            raise ValueError("消息不能为空")

        async with self._chat_lock:
            self._ensure_page_open()
            before_count = await self._assistant_count()
            LOGGER.info("正在发送消息")
            await self._send_text(text)
            await self._wait_for_new_assistant(before_count)
            await self._wait_for_response_complete()
            answer = await self._get_last_assistant_text()
            LOGGER.info("ChatGPT 回复生成完成")
            return answer

    async def __aenter__(self) -> "ChatGPTSession":
        self._ensure_page_open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._shutdown()

    def _ensure_page_open(self) -> None:
        if self._closed or self.page.is_closed():
            raise ChatGPTBridgeError("当前 ChatGPT 标签页已关闭")

    async def _wait_page_ready(self) -> None:
        """等待输入框出现，也给首次手动登录留下可见操作时间。"""

        self._ensure_page_open()
        prompt = self.page.locator(",".join(PROMPT_SELECTORS)).first
        try:
            await prompt.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ChatGPTBridgeError(
                "未找到 ChatGPT 输入框，可能尚未登录、网络异常或页面结构发生变化"
            ) from exc

    async def _get_prompt_locator(self) -> Locator:
        self._ensure_page_open()
        for selector in PROMPT_SELECTORS:
            locator = self.page.locator(selector).first
            try:
                if await locator.is_visible():
                    return locator
            except PlaywrightError:
                continue
        raise ChatGPTBridgeError(
            "未找到 ChatGPT 输入框，可能尚未登录或页面结构发生变化"
        )

    async def _get_send_button(self) -> Locator | None:
        self._ensure_page_open()
        for selector in SEND_BUTTON_SELECTORS:
            locator = self.page.locator(selector).first
            try:
                if await locator.is_visible():
                    return locator
            except PlaywrightError:
                continue
        return None

    async def _assistant_count(self) -> int:
        self._ensure_page_open()
        try:
            return await self.page.locator(ASSISTANT_SELECTOR).count()
        except PlaywrightError as exc:
            raise ChatGPTBridgeError(
                "读取 Assistant 消息失败，可能由于页面结构发生变化"
            ) from exc

    async def _send_text(self, text: str) -> None:
        prompt = await self._get_prompt_locator()
        try:
            await prompt.click()
            try:
                await prompt.fill(text)
            except PlaywrightError:
                await prompt.click()
                await self.page.keyboard.insert_text(text)

            current_text = await self._read_prompt_text(prompt)
            if self._normalize_text(current_text) != self._normalize_text(text):
                await prompt.click()
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.insert_text(text)
                current_text = await self._read_prompt_text(prompt)

            if self._normalize_text(current_text) != self._normalize_text(text):
                raise ChatGPTBridgeError("文本未成功写入 ChatGPT 输入框")

            button = await self._get_send_button()
            if button is not None:
                if not await button.is_enabled():
                    raise ChatGPTBridgeError("ChatGPT 发送按钮当前不可用")
                await button.click()
            else:
                # 只有确认焦点仍在输入框且文本已验证时，才使用 Enter 发送。
                await prompt.click()
                await self.page.keyboard.press("Enter")
        except ChatGPTBridgeError:
            raise
        except PlaywrightError as exc:
            raise ChatGPTBridgeError(
                "发送消息失败，可能由于 ChatGPT 页面结构发生变化"
            ) from exc

    async def _read_prompt_text(self, prompt: Locator) -> str:
        try:
            return await prompt.input_value()
        except PlaywrightError:
            try:
                return await prompt.inner_text()
            except PlaywrightError as exc:
                raise ChatGPTBridgeError("无法读取 ChatGPT 输入框内容") from exc

    async def _wait_for_new_assistant(self, old_count: int) -> None:
        deadline = time.monotonic() + RESPONSE_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            if await self._assistant_count() > old_count:
                LOGGER.info("已检测到新的 Assistant 消息")
                return
            await asyncio.sleep(POLL_INTERVAL_MS / 1000)
        raise ChatGPTBridgeError("等待 ChatGPT 回复超时")

    async def _is_generating(self) -> bool:
        self._ensure_page_open()
        for selector in STOP_BUTTON_SELECTORS:
            locator = self.page.locator(selector).first
            try:
                if await locator.is_visible():
                    return True
            except PlaywrightError:
                continue
        return False

    async def _get_last_assistant_locator(self) -> Locator:
        count = await self._assistant_count()
        if count == 0:
            raise ChatGPTBridgeError("未找到 Assistant 回复")
        return self.page.locator(ASSISTANT_SELECTOR).nth(count - 1)

    async def _get_last_assistant_text(self) -> str:
        assistant = await self._get_last_assistant_locator()
        try:
            content = (await assistant.inner_text()).strip()
        except PlaywrightError as exc:
            raise ChatGPTBridgeError(
                "读取 Assistant 回复失败，可能由于页面结构发生变化"
            ) from exc
        if not content:
            raise ChatGPTBridgeError("未读取到 Assistant 回复")
        return content

    async def _wait_for_response_complete(self) -> None:
        deadline = time.monotonic() + RESPONSE_TIMEOUT_MS / 1000
        last_text: str | None = None
        stable_since: float | None = None

        while time.monotonic() < deadline:
            assistant = await self._get_last_assistant_locator()
            try:
                current_text = (await assistant.inner_text()).strip()
            except PlaywrightError as exc:
                raise ChatGPTBridgeError(
                    "等待 Assistant 回复失败，可能由于页面结构发生变化"
                ) from exc

            now = time.monotonic()
            if current_text != last_text:
                last_text = current_text
                stable_since = now if current_text else None
            elif current_text and stable_since is not None:
                stable_for_ms = (now - stable_since) * 1000
                if stable_for_ms >= STABLE_TIME_MS and not await self._is_generating():
                    return

            await asyncio.sleep(POLL_INTERVAL_MS / 1000)

        raise ChatGPTBridgeError("等待 ChatGPT 回复超时")

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.split())

    async def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._context.close()
        except PlaywrightError as exc:
            LOGGER.warning("关闭 ChatGPT 浏览器上下文失败：%s", exc)
        finally:
            await self._playwright.stop()


# =========================
# CLI test program
# =========================


def _print_history(messages: list[dict[str, str]]) -> None:
    for message in messages:
        print(f"[{message['role']}]")
        print(message["content"])
        print()


async def main() -> None:
    url = input("请输入 ChatGPT URL：\n> ").strip()
    if not url:
        print("错误：URL 不能为空")
        return

    session: ChatGPTSession | None = None
    try:
        print("正在打开 ChatGPT...")
        session = await ChatGPTSession.open(url)
        messages = await session.get_messages()
        print("ChatGPT 页面已绑定。")
        print(f"当前 URL: {session.page.url}")
        print(f"已读取 {len(messages)} 条消息。")

        while True:
            try:
                command = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if command in {"/exit", "/quit"}:
                break
            if command == "/history":
                _print_history(await session.get_messages())
                continue
            if not command:
                continue

            try:
                answer = await session.chat(command)
                print(f"ChatGPT > {answer}")
            except (ChatGPTBridgeError, ValueError) as exc:
                LOGGER.error("%s", exc)
                print(f"错误：{exc}")
    except (ChatGPTBridgeError, ValueError) as exc:
        LOGGER.error("%s", exc)
        print(f"错误：{exc}")
    finally:
        if session is not None:
            await session._shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main())
