"""Start the Broker if needed and enter the interactive console."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_llm_bridge.cli.launcher import manual_main


if __name__ == "__main__":
    raise SystemExit(manual_main())
