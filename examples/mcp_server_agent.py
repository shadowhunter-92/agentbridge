"""Source-checkout wrapper for the packaged synthetic demo."""
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    runpy.run_module("src.demos.mcp_server_agent", run_name="__main__")
