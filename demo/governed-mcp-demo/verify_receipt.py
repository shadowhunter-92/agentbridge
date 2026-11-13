"""Existing offline verifier wrapper. Public roots/expected action are explicit."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.governance.evidence_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
