"""Synthetic transfer MCP tool wrapper; no Stripe SDK or API is used."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.governed_mcp_tool import main

if __name__ == "__main__":
    main()
