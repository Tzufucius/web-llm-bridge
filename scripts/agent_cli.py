"""Start the Broker if needed and run one Agent CLI command."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web_llm_bridge.cli.launcher import agent_main


if __name__ == "__main__":
    raise SystemExit(agent_main())
