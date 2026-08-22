"""面向 Shell Agent 的 Broker 客户端命令。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from ..client import rpc_call
from ..errors import WebLLMBridgeError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send one command to the local Web LLM Broker.")
    commands = parser.add_subparsers(dest="command", required=True)
    opened = commands.add_parser("open", help="Open, create, or restore a browser session.")
    group = opened.add_mutually_exclusive_group()
    group.add_argument("--new", action="store_true", help="Create a new conversation.")
    group.add_argument("--url", help="Open or restore this conversation URL.")
    group.add_argument("--session-id", help="Restore a persisted session by ID.")
    opened.add_argument("--provider", default="chatgpt", help="Provider ID (default: chatgpt).")
    opened.add_argument("--reopen-on-closed", action="store_true", default=None, help="Reopen a closed browser tab when possible.")
    opened.add_argument("--json", action="store_true", help="Write one JSON object to stdout.")
    chat = commands.add_parser("chat", help="Send one prompt and wait for the response.")
    text_source = chat.add_mutually_exclusive_group(required=True)
    text_source.add_argument("--text", help="Prompt text.")
    text_source.add_argument("--stdin", action="store_true", help="Read the prompt from stdin.")
    chat.add_argument("--session-id", help="Target session ID; defaults to the active session.")
    chat.add_argument("--provider", default="chatgpt", help="Provider ID (default: chatgpt).")
    chat.add_argument("--json", action="store_true", help="Write one JSON object to stdout.")
    history = commands.add_parser("get-messages", help="Read messages from the bound browser tab.")
    history.add_argument("--limit", type=int, default=5, help="Maximum messages to return (default: 5).")
    history.add_argument("--all", action="store_true", dest="full", help="Return the complete collected history.")
    history.add_argument("--session-id", help="Target session ID; defaults to the active session.")
    history.add_argument("--provider", default="chatgpt", help="Provider ID (default: chatgpt).")
    history.add_argument("--json", action="store_true", help="Write one JSON object to stdout.")
    listed = commands.add_parser("list-sessions", help="List persisted sessions.")
    listed.add_argument("--provider", default="chatgpt", help="Provider ID (default: chatgpt).")
    listed.add_argument("--json", action="store_true", help="Write one JSON object to stdout.")
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


def _emit_error(args: argparse.Namespace, *, code: str, message: str, safe_to_retry: bool = False) -> int:
    if args.json:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": code,
                        "message": message,
                        "safe_to_retry": safe_to_retry,
                    },
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"Error: {message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    # Keep argparse's native exit code and diagnostics for invalid command lines.
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
        if args.json:
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        elif "text" in result:
            print(result["text"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except WebLLMBridgeError as exc:
        return _emit_error(args, code=exc.code, message=str(exc), safe_to_retry=exc.safe_to_retry)
    except Exception as exc:
        return _emit_error(args, code="INTERNAL_ERROR", message=str(exc) or "Internal error")


if __name__ == "__main__":
    raise SystemExit(main())
