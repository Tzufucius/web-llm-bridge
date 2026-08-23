"""本地 NDJSON Broker 服务端。"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
from typing import Any

from ..errors import WebLLMBridgeError
from ..protocol import BRIDGE_HOST, BROKER_PORT, DEFAULT_HISTORY_LIMIT, MAX_MESSAGE_BYTES, error_response
from ..session.manager import SessionManager


class BrokerServer:
    def __init__(self, manager: SessionManager | None = None) -> None:
        self.manager = manager or SessionManager()
        self._server: asyncio.AbstractServer | None = None

    async def handle_request(self, request: dict[str, Any], progress_sink: Any = None) -> dict[str, Any]:
        request_id = request.get("id") if isinstance(request, dict) else None
        if not isinstance(request_id, str) or not request_id:
            return error_response(request_id, "INVALID_REQUEST", "缺少有效 id")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str):
            return error_response(request_id, "INVALID_REQUEST", "缺少有效 method")
        if not isinstance(params, dict):
            return error_response(request_id, "INVALID_ARGUMENT", "params 必须是对象")
        try:
            provider = params.get("provider", "chatgpt")
            session_id = params.get("session_id")
            if session_id is not None and not isinstance(session_id, str):
                raise WebLLMBridgeError("session_id 参数必须是字符串", "INVALID_ARGUMENT")
            if method == "open":
                result = await self.manager.open(provider=provider, new=params.get("new", False), url=params.get("url"), session_id=session_id, reopen_on_closed=params.get("reopen_on_closed"))
            elif method == "chat":
                result = await self.manager.chat(params.get("text"), provider=provider, session_id=session_id, progress=progress_sink)
            elif method == "get_messages":
                result = await self.manager.get_messages(provider=provider, session_id=session_id, limit=params.get("limit", DEFAULT_HISTORY_LIMIT), full=params.get("full", False))
            elif method == "debug_snapshot":
                result = await self.manager.debug_snapshot(provider=provider, session_id=session_id)
            elif method == "debug_trace":
                trace_request_id = params.get("request_id")
                if not isinstance(trace_request_id, str) or not trace_request_id:
                    raise WebLLMBridgeError("request_id 参数为必填字符串", "INVALID_ARGUMENT")
                result = await self.manager.debug_trace(provider=provider, session_id=session_id, request_id=trace_request_id)
            elif method == "wait_artifact":
                artifact_id = params.get("artifact_id")
                if not isinstance(artifact_id, str) or not artifact_id:
                    raise WebLLMBridgeError("artifact_id 参数为必填字符串", "INVALID_ARGUMENT")
                timeout_ms = params.get("timeout_ms", 60_000)
                if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 1_000 <= timeout_ms <= 300_000:
                    raise WebLLMBridgeError("timeout_ms 必须是 1000 到 300000 的整数", "INVALID_ARGUMENT")
                result = await self.manager.wait_artifact(artifact_id, timeout_ms=timeout_ms)
            elif method == "close_session":
                result = await self.manager.close_session(provider=provider, session_id=session_id)
            elif method == "forget_session":
                if not isinstance(session_id, str) or not session_id:
                    raise WebLLMBridgeError("session_id 参数为必填字符串", "INVALID_ARGUMENT")
                result = await self.manager.forget_session(provider=provider, session_id=session_id)
            elif method == "get_artifact":
                artifact_id = params.get("artifact_id")
                if not isinstance(artifact_id, str) or not artifact_id:
                    raise WebLLMBridgeError("artifact_id 参数为必填字符串", "INVALID_ARGUMENT")
                output = params.get("output")
                if output is not None and not isinstance(output, str):
                    raise WebLLMBridgeError("output 参数必须是字符串", "INVALID_ARGUMENT")
                result = await self.manager.get_artifact(artifact_id, output=output)
            elif method == "list_sessions":
                listed_provider = params.get("provider")
                if listed_provider is not None and not isinstance(listed_provider, str):
                    raise WebLLMBridgeError("provider 参数必须是字符串", "INVALID_ARGUMENT")
                result = {"sessions": await self.manager.list_sessions(listed_provider)}
            else:
                return error_response(request_id, "UNKNOWN_METHOD", f"未知方法：{method}")
            return {"id": request_id, "ok": True, "result": result}
        except WebLLMBridgeError as exc:
            return error_response(request_id, exc.code, str(exc), safe_to_retry=exc.safe_to_retry)
        except (TypeError, ValueError) as exc:
            return error_response(request_id, "INVALID_ARGUMENT", str(exc))
        except Exception:
            return error_response(request_id, "INTERNAL_ERROR", "Broker 内部错误")

    async def start(self, host: str = BRIDGE_HOST, port: int = BROKER_PORT) -> None:
        if self._server is None:
            self._server = await asyncio.start_server(self._handle_client, host, port, limit=MAX_MESSAGE_BYTES + 1)

    async def serve_forever(self) -> None:
        await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self.manager.close()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        write_lock = asyncio.Lock()
        tasks: set[asyncio.Task[Any]] = set()

        async def send(message: dict[str, Any]) -> None:
            payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            if len(payload) > MAX_MESSAGE_BYTES + 1:
                payload = (
                    json.dumps(
                        error_response(
                            message.get("id"),
                            "RESPONSE_TOO_LARGE",
                            "Broker 响应超过 8 MiB 限制",
                        ),
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
            async with write_lock:
                writer.write(payload)
                await writer.drain()

        async def process(raw: bytes) -> None:
            try:
                request = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                await send(error_response(None, "INVALID_JSON", "请求不是有效 JSON"))
                return
            if not isinstance(request, dict):
                await send(error_response(None, "INVALID_REQUEST", "请求必须是 JSON 对象"))
                return
            progress_tasks: list[asyncio.Task[Any]] = []
            request_id = request.get("id")
            def progress(event: dict[str, Any]) -> None:
                progress_tasks.append(asyncio.create_task(send({"type": "progress", "id": request_id, "provider": request.get("params", {}).get("provider", "chatgpt"), "session_id": request.get("params", {}).get("session_id"), "tab_id": event.get("tab_id"), "url": event.get("url", ""), "phase": event.get("phase"), "elapsed_ms": event.get("elapsed_ms", 0), "idle_ms": event.get("idle_ms", 0)})))
            response = await self.handle_request(request, progress)
            if progress_tasks:
                await asyncio.gather(*progress_tasks, return_exceptions=True)
            await send(response)

        try:
            while True:
                try:
                    line = await reader.readline()
                except ValueError:
                    await send(error_response(None, "INVALID_ARGUMENT", "请求行过大"))
                    break
                if not line:
                    break
                if len(line) > MAX_MESSAGE_BYTES + 1:
                    await send(error_response(None, "INVALID_ARGUMENT", "请求行过大"))
                    break
                task = asyncio.create_task(process(line.rstrip(b"\r\n")))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            await writer.wait_closed()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the persistent local Web LLM Broker.")
    parser.add_argument("command", nargs="?", choices=["serve"], default="serve", help="Start serving Broker and Extension connections.")
    parser.parse_args(argv)
    try:
        asyncio.run(BrokerServer().serve_forever())
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        logging.getLogger(__name__).error("Broker 启动失败：%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
