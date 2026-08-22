import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from web_llm_bridge.cli.agent import main


class AgentCliTests(unittest.TestCase):
    def test_stdin_and_json_emit_one_stdout_result(self) -> None:
        output = io.StringIO()
        with patch("web_llm_bridge.cli.agent.rpc_call", AsyncMock(return_value={"text": "answer"})), patch("sys.stdin", io.StringIO("question")), redirect_stdout(output):
            self.assertEqual(main(["chat", "--stdin", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"text": "answer"})
