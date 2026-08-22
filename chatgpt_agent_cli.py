"""面向 Shell Agent 的 Persistent Broker NDJSON client。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any
from uuid import uuid4

try:
    from .chatgpt_broker import AGENT_HOST, AGENT_PORT
except ImportError:  # direct script execution
    from chatgpt_broker import AGENT_HOST, AGENT_PORT  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChatGPT Agent Broker client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    open_parser = subparsers.add_parser("open", help="打开或恢复 Session")
    open_group = open_parser.add_mutually_exclusive_group()
    open_group.add_argument("--new", action="store_true", help="新建 Conversation")
    open_group.add_argument("--url", help="指定 Conversation URL")
    open_group.add_argument("--session-id", help="按 Session ID 恢复")
    open_parser.add_argument("--json", action="store_true")

    chat_parser = subparsers.add_parser("chat", help="发送消息")
    text_group = chat_parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text")
    text_group.add_argument("--stdin", action="store_true")
    chat_parser.add_argument("--json", action="store_true")

    history_parser = subparsers.add_parser("get-messages", help="读取历史消息")
    history_parser.add_argument("--limit", type=int, default=5)
    history_parser.add_argument("--all", action="store_true", dest="full")
    history_parser.add_argument("--json", action="store_true")

    list_parser = subparsers.add_parser("list-sessions", help="列出历史 Session")
    list_parser.add_argument("--json", action="store_true")
    return parser


async def rpc_call(method: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request_id = str(uuid4())
    reader, writer = await asyncio.open_connection(AGENT_HOST, AGENT_PORT)
    progress: list[dict[str, Any]] = []
    try:
        request = {
            "id": request_id,
            "method": method,
            "params": params,
        }
        writer.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        while True:
            line = await reader.readline()
            if not line:
                raise ConnectionError("Broker 在返回结果前断开连接")
            message = json.loads(line.decode("utf-8"))
            if message.get("type") == "progress" and message.get("id") == request_id:
                progress.append(message)
                print(
                    f"ChatGPT {message.get('phase', 'working')}...",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            if message.get("id") == request_id:
                return message, progress
    finally:
        writer.close()
        await writer.wait_closed()


def _print_result(response: dict[str, Any], json_mode: bool) -> int:
    if json_mode:
        print(json.dumps(response, ensure_ascii=False))
    elif response.get("ok") is True:
        result = response.get("result", {})
        if isinstance(result, dict) and "text" in result:
            print(result["text"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        error = response.get("error") or {}
        print(f"错误 [{error.get('code', 'INTERNAL_ERROR')}]：{error.get('message', 'Broker 请求失败')}", file=sys.stderr)
    return 0 if response.get("ok") is True else 1


async def _async_main(args: argparse.Namespace) -> int:
    if args.command == "open":
        params: dict[str, Any] = {}
        if args.new:
            params["new"] = True
        elif args.url:
            params["url"] = args.url
        elif args.session_id:
            params["session_id"] = args.session_id
        response, _ = await rpc_call("open", params)
        return _print_result(response, args.json)

    if args.command == "chat":
        text = args.text if args.text is not None else sys.stdin.read()
        response, _ = await rpc_call("chat", {"text": text})
        return _print_result(response, args.json)

    if args.command == "get-messages":
        params = {"limit": args.limit, "full": args.full}
        response, _ = await rpc_call("get_messages", params)
        return _print_result(response, args.json)

    if args.command == "list-sessions":
        response, _ = await rpc_call("list_sessions", {})
        return _print_result(response, args.json)

    return 2


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except (ConnectionError, OSError) as exc:
        print(f"Broker 未运行或无法连接：{exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"Broker 返回无效 JSON：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
