"""Deterministic source-checkout CLI; no LangChain/LLM claim."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.governed_mcp_demo import main

if __name__ == "__main__":
    raise SystemExit(main())
