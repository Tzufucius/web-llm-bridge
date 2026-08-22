"""通过本机 Broker 发送一条 ChatGPT 消息的最小 NDJSON 示例。"""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import uuid4


HOST = "127.0.0.1"
PORT = 8766


async def rpc(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, method: str, params: dict) -> dict:
    request_id = str(uuid4())
    writer.write(
        (json.dumps({"id": request_id, "method": method, "params": params}, ensure_ascii=False) + "\n").encode()
    )
    await writer.drain()

    while line := await reader.readline():
        message = json.loads(line)
        if message.get("type") == "progress":
            print(f"[progress] {message.get('phase', 'working')}", file=sys.stderr)
            continue
        if message.get("id") == request_id:
            if message.get("ok") is not True:
                error = message.get("error", {})
                raise RuntimeError(f"{error.get('code', 'INTERNAL_ERROR')}: {error.get('message', '请求失败')}")
            return message

    raise ConnectionError("Broker 在返回结果前断开连接")


async def main(prompt: str) -> None:
    reader, writer = await asyncio.open_connection(HOST, PORT)
    try:
        await rpc(reader, writer, "open", {"new": True})
        response = await rpc(reader, writer, "chat", {"text": prompt})
        print(response["result"].get("text", json.dumps(response["result"], ensure_ascii=False)))
    finally:
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if not prompt:
        raise SystemExit("请在参数或 stdin 中提供 Prompt")
    asyncio.run(main(prompt))
