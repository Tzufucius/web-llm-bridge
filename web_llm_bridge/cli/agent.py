"""面向 Shell Agent 的 Broker 客户端命令。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from ..client import rpc_call


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Web LLM Broker client")
    commands = parser.add_subparsers(dest="command", required=True)
    opened = commands.add_parser("open")
    group = opened.add_mutually_exclusive_group()
    group.add_argument("--new", action="store_true")
    group.add_argument("--url")
    group.add_argument("--session-id")
    opened.add_argument("--provider", default="chatgpt")
    opened.add_argument("--reopen-on-closed", action="store_true", default=None)
    opened.add_argument("--json", action="store_true")
    chat = commands.add_parser("chat")
    text_source = chat.add_mutually_exclusive_group(required=True)
    text_source.add_argument("--text")
    text_source.add_argument("--stdin", action="store_true")
    chat.add_argument("--session-id")
    chat.add_argument("--provider", default="chatgpt")
    chat.add_argument("--json", action="store_true")
    history = commands.add_parser("get-messages")
    history.add_argument("--limit", type=int, default=5)
    history.add_argument("--all", action="store_true", dest="full")
    history.add_argument("--session-id")
    history.add_argument("--provider", default="chatgpt")
    history.add_argument("--json", action="store_true")
    listed = commands.add_parser("list-sessions")
    listed.add_argument("--provider", default="chatgpt")
    listed.add_argument("--json", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "open":
        return await rpc_call("open", {"provider": args.provider, "new": args.new, "url": args.url, "session_id": args.session_id, "reopen_on_closed": args.reopen_on_closed})
    if args.command == "chat":
        text = sys.stdin.read() if args.stdin else args.text
        def progress(event: dict[str, Any]) -> None:
            print(f"[{event.get('phase', 'working')}]", file=sys.stderr, flush=True)
        return await rpc_call("chat", {"provider": args.provider, "session_id": args.session_id, "text": text}, progress=progress)
    if args.command == "get-messages":
        return await rpc_call("get_messages", {"provider": args.provider, "session_id": args.session_id, "limit": args.limit, "full": args.full})
    return await rpc_call("list_sessions", {"provider": args.provider})


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = asyncio.run(_run(args))
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif "text" in result:
            print(result["text"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
