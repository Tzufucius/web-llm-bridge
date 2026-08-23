import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, patch

from web_llm_bridge.cli.agent import main
from web_llm_bridge.errors import WebLLMBridgeError


class AgentCliTests(unittest.TestCase):
    def test_stdin_and_json_emit_success_envelope(self) -> None:
        output = io.StringIO()
        with patch("web_llm_bridge.cli.agent.rpc_call", AsyncMock(return_value={"text": "answer"})), patch("sys.stdin", io.StringIO("question")), redirect_stdout(output):
            self.assertEqual(main(["chat", "--stdin", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"ok": True, "result": {"text": "answer"}})

    def test_json_business_error_is_machine_readable(self) -> None:
        output = io.StringIO()
        error = WebLLMBridgeError("状态未知", "CHAT_STATE_UNKNOWN")
        with patch("web_llm_bridge.cli.agent.rpc_call", AsyncMock(side_effect=error)), redirect_stdout(output):
            self.assertNotEqual(main(["chat", "--text", "question", "--json"]), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], {"code": "CHAT_STATE_UNKNOWN", "message": "状态未知", "safe_to_retry": False})

    def test_json_unexpected_error_uses_internal_error(self) -> None:
        output = io.StringIO()
        with patch("web_llm_bridge.cli.agent.rpc_call", AsyncMock(side_effect=RuntimeError("boom"))), redirect_stdout(output):
            self.assertEqual(main(["chat", "--text", "question", "--json"]), 1)

        self.assertEqual(
            json.loads(output.getvalue()),
            {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "boom", "safe_to_retry": False}},
        )

    def test_progress_stays_on_stderr(self) -> None:
        async def fake_rpc_call(method: str, params: dict, *, progress=None, **_: object) -> dict:
            if progress:
                progress({"phase": "thinking"})
            return {"text": "answer"}

        output = io.StringIO()
        diagnostics = io.StringIO()
        with patch("web_llm_bridge.cli.agent.rpc_call", side_effect=fake_rpc_call), patch("sys.stdin", io.StringIO("question")), redirect_stdout(output), redirect_stderr(diagnostics):
            self.assertEqual(main(["chat", "--stdin", "--json"]), 0)

        self.assertEqual(json.loads(output.getvalue()), {"ok": True, "result": {"text": "answer"}})
        self.assertEqual(diagnostics.getvalue(), "[thinking]\n")

    def test_non_json_success_remains_human_readable(self) -> None:
        output = io.StringIO()
        with patch("web_llm_bridge.cli.agent.rpc_call", AsyncMock(return_value={"text": "answer"})), redirect_stdout(output):
            self.assertEqual(main(["chat", "--text", "question"]), 0)
        self.assertEqual(output.getvalue(), "answer\n")

    def test_non_json_error_remains_human_readable(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with patch("web_llm_bridge.cli.agent.rpc_call", AsyncMock(side_effect=WebLLMBridgeError("坏请求", "INVALID_ARGUMENT"))), redirect_stdout(output), redirect_stderr(error):
            self.assertEqual(main(["chat", "--text", "question"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(error.getvalue(), "Error: 坏请求\n")

    def test_debug_snapshot_calls_sanitized_rpc(self) -> None:
        output = io.StringIO()
        with patch("web_llm_bridge.cli.agent.rpc_call", AsyncMock(return_value={"snapshot": {"generating": False}})), redirect_stdout(output):
            self.assertEqual(main(["debug-snapshot", "--session-id", "session", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["result"]["snapshot"]["generating"], False)

    def test_debug_trace_requires_and_forwards_request_id(self) -> None:
        output = io.StringIO()
        fake = AsyncMock(return_value={"trace": {"request_id": "request"}})
        with patch("web_llm_bridge.cli.agent.rpc_call", fake), redirect_stdout(output):
            self.assertEqual(main(["debug-trace", "--request-id", "request", "--session-id", "session", "--json"]), 0)
        self.assertEqual(fake.await_args.args[0], "debug_trace")
        self.assertEqual(fake.await_args.args[1]["request_id"], "request")

    def test_wait_artifact_forwards_timeout(self) -> None:
        output = io.StringIO()
        fake = AsyncMock(return_value={"id": "img_test", "ready": True})
        with patch("web_llm_bridge.cli.agent.rpc_call", fake), redirect_stdout(output):
            self.assertEqual(main(["wait-artifact", "--id", "img_test", "--timeout-ms", "1200", "--json"]), 0)
        self.assertEqual(fake.await_args.args[0], "wait_artifact")
        self.assertEqual(fake.await_args.args[1]["timeout_ms"], 1200)
