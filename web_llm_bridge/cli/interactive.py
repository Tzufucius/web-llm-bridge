"""人机交互式 Broker 客户端。"""

from __future__ import annotations

import asyncio
import sys

from ..session.model import WebLLMSession


async def _run() -> int:
    target = await asyncio.to_thread(input, "会话（回车恢复，new 新建，或输入 URL）> ")
    if target.strip().lower() == "new":
        session = await WebLLMSession.open(new=True)
    elif target.strip():
        session = await WebLLMSession.open(url=target.strip())
    else:
        session = await WebLLMSession.open()

    def progress(event: dict[str, object]) -> None:
        print(f"[{event.get('phase', 'working')}]", file=sys.stderr, flush=True)

    while True:
        text = await asyncio.to_thread(input, "You> ")
        if text.strip() in {"/quit", "/exit"}:
            return 0
        if text.strip() == "/new":
            session = await WebLLMSession.open(new=True)
            continue
        if text.startswith("/open "):
            session = await WebLLMSession.open(url=text.removeprefix("/open ").strip())
            continue
        if text.startswith("/history"):
            option = text.removeprefix("/history").strip().lower()
            full = option == "all"
            limit = None if full else (int(option) if option.isdigit() else 5)
            for message in await session.get_messages(limit=limit, full=full):
                print(f"{message['role']}: {message['content']}")
            continue
        if text.strip() == "/sessions":
            from ..client import WebLLMClient
            for item in await WebLLMClient().list_sessions():
                print(f"{item['session_id']} {item['provider']} {item['current_url']}")
            continue
        print(await session.chat(text, progress=progress))


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
