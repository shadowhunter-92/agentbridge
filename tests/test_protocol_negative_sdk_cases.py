"""Explicit SDK negative schema checks for narrow reviewed wire subsets.

These checks do not establish transport or full protocol conformance.
They document invalid message shapes rejected by the installed SDK families.
"""
import pytest
from pydantic import ValidationError


def test_official_mcp_call_tool_schema_rejects_missing_name():
    mcp = pytest.importorskip("mcp.types")
    with pytest.raises(ValidationError):
        mcp.CallToolRequestParams.model_validate({"arguments": {"safe": True}})


def test_official_a2a_task_schema_rejects_incomplete_task():
    a2a = pytest.importorskip("a2a.types")
    with pytest.raises(ValidationError):
        a2a.Task.model_validate({"id": "incomplete-task"})


def test_protocol_subset_is_explicit_not_full_conformance():
    from pathlib import Path
    note = (Path(__file__).resolve().parents[1] /
            "docs/PROTOCOL_COMPATIBILITY_2026.md").read_text()
    for phrase in ("NOT complete protocol conformance", "MCP", "A2A",
                   "MCP stdio", "A2A 1.0"):
        assert phrase in note
