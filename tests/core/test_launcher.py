import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from web_llm_bridge.cli import launcher


class LauncherTests(unittest.TestCase):
    def test_running_broker_is_reused(self) -> None:
        with patch.object(launcher, "broker_is_running", return_value=True), patch.object(
            launcher.subprocess, "Popen"
        ) as popen:
            launcher.ensure_broker()
        popen.assert_not_called()

    def test_broker_is_started_with_current_python(self) -> None:
        process = MagicMock(pid=42)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            launcher.os.environ, {"WEB_LLM_BRIDGE_HOME": directory}
        ), patch.object(
            launcher, "broker_is_running", side_effect=[False, True]
        ), patch.object(
            launcher.subprocess, "Popen", return_value=process
        ) as popen:
            launcher.ensure_broker()

            self.assertEqual(
                (Path(directory) / "runtime" / "broker.pid").read_text(encoding="ascii"),
                "42",
            )
        self.assertEqual(popen.call_args.args[0][0], launcher.sys.executable)

    def test_help_does_not_start_broker(self) -> None:
        with patch.object(launcher, "ensure_broker") as ensure, patch(
            "web_llm_bridge.cli.agent.main", return_value=0
        ):
            self.assertEqual(launcher.agent_main(["--help"]), 0)
        ensure.assert_not_called()
