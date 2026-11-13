"""Bounded actual MCP attack demonstrations; no remote endpoint or money."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("double-spend", "bypass-approval", "split-brain"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scenario = {"double-spend": "success", "bypass-approval": "denied", "split-brain": "split-brain"}[args.scenario]
    # Reuse the bounded main path including its independent watchdog.
    from examples.governed_mcp_demo import main
    sys.argv = [sys.argv[0], "--output", str(args.output), "--scenario", scenario]
    raise SystemExit(main())
