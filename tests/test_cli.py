"""
Smoke tests for the AgentBridge CLI (src/cli.py) — runs it as a real subprocess
(`python -m src ...`) so the entrypoint, arg parsing, and a real translation are covered.
"""

import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "src", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )


def test_cli_version():
    r = _cli("--version")
    assert r.returncode == 0, r.stderr
    assert "AgentBridge" in r.stdout


def test_cli_help_lists_commands():
    r = _cli()  # no args -> help
    assert r.returncode == 0, r.stderr
    assert "serve" in r.stdout and "translate" in r.stdout


def test_cli_translate_openai_to_mcp():
    r = _cli("translate", "--from", "openai", "--to", "mcp", "--tool", "add", "--args", '{"a":2,"b":3}')
    assert r.returncode == 0, r.stderr
    assert "openai -> mcp" in r.stdout
    assert "tools/call" in r.stdout  # the MCP wire shape proves a real translation happened
