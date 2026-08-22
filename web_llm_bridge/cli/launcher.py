"""Cross-platform launch helpers for the broker-backed CLIs."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Sequence

from ..protocol import BRIDGE_HOST, BROKER_PORT


def _bridge_home() -> Path:
    configured = os.environ.get("WEB_LLM_BRIDGE_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".web-llm-bridge"


def broker_is_running(timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((BRIDGE_HOST, BROKER_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_broker(timeout: float = 5.0) -> None:
    """Start a detached Broker unless one is already listening."""
    if broker_is_running():
        return

    runtime_dir = _bridge_home() / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = runtime_dir / "broker.stdout.log"
    stderr_path = runtime_dir / "broker.stderr.log"
    creationflags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "web_llm_bridge.broker.server", "serve"],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
    (runtime_dir / "broker.pid").write_text(str(process.pid), encoding="ascii")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if broker_is_running():
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise RuntimeError(f"Broker failed to start. See {stderr_path}")


def manual_main(argv: Sequence[str] | None = None) -> int:
    from .interactive import main

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "install":
        from .skill_install import main as install_main

        return install_main(arguments[1:])
    if not arguments or any(argument in {"-h", "--help"} for argument in arguments):
        from .skill_install import warn_if_stale

        warn_if_stale()
    if not any(argument in {"-h", "--help"} for argument in arguments):
        ensure_broker()
    return main(arguments)


def agent_main(argv: Sequence[str] | None = None) -> int:
    from .agent import main

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not any(argument in {"-h", "--help"} for argument in arguments):
        ensure_broker()
    return main(arguments)
