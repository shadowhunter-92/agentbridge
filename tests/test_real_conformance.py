"""
Real-SDK Conformance Tests
==========================
Validates the bridge's translation output against the *official* protocol SDKs,
not against the bridge's own assumptions. This is the test that catches the
"works on mocks, rejected by real agents" class of bug.

- MCP side:  Anthropic's official `mcp` package (mcp.types)
- A2A side:  Google's official `a2a-sdk` JSON-RPC pydantic types (a2a.types),
             pinned to the 0.3.x line that ships the JSON-RPC transport models.

If either SDK is not installed, the relevant tests are skipped (they are dev
dependencies, not runtime dependencies of the bridge).

Run: pytest tests/test_real_conformance.py -v
"""

import sys
import pytest
from unittest.mock import MagicMock

# The API/persistence modules import redis at module load; the engine does not,
# but we mock redis here too so the whole package imports cleanly under test.
sys.modules.setdefault("redis", MagicMock())
sys.modules.setdefault("redis.asyncio", MagicMock())

from src.engine.translation_engine import TranslationEngine, TranslationDirection

mcp_types = pytest.importorskip("mcp.types", reason="official mcp SDK not installed")
a2a_types = pytest.importorskip("a2a.types", reason="official a2a-sdk not installed")


@pytest.fixture
def engine():
    return TranslationEngine()


class TestMcpToA2AConformance:
    """The bridge's MCP->A2A output must be a valid A2A Task per the official SDK."""

    def test_tools_call_produces_valid_a2a_task(self, engine):
        mcp_request = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"q": "hello"}},
        }
        result = engine.translate(mcp_request, TranslationDirection.MCP_TO_A2A.value)
        assert result.success
        task = result.target_data["task"]

        # Must validate against the REAL A2A Task schema (history/contextId/kind).
        validated = a2a_types.Task.model_validate(task)
        assert validated.id
        assert validated.context_id
        assert validated.history, "A2A Task must carry the message under `history`"

    def test_resources_read_produces_valid_a2a_task(self, engine):
        mcp_request = {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "resources/read",
            "params": {"uri": "file:///tmp/x.txt"},
        }
        result = engine.translate(mcp_request, TranslationDirection.MCP_TO_A2A.value)
        a2a_types.Task.model_validate(result.target_data["task"])


class TestA2AToMcpConformance:
    """The bridge's A2A->MCP output must be valid MCP per the official SDK."""

    def test_tool_call_params_match_mcp_schema(self, engine):
        a2a_request = {
            "jsonrpc": "2.0",
            "id": "9",
            "method": "tasks/send",
            "params": {
                "task": {
                    "history": [
                        {
                            "kind": "message",
                            "messageId": "m1",
                            "role": "user",
                            "parts": [
                                {
                                    "kind": "data",
                                    "data": {
                                        "name": "search",
                                        "arguments": {"q": "hello"},
                                    },
                                }
                            ],
                        }
                    ]
                }
            },
        }
        result = engine.translate(a2a_request, TranslationDirection.A2A_TO_MCP.value)
        assert result.success
        params = result.target_data["params"]

        # Real MCP tools/call params require `name` (not `tool_name`).
        validated = mcp_types.CallToolRequestParams.model_validate(params)
        assert validated.name == "search"
        assert validated.arguments == {"q": "hello"}

    def test_accepts_real_mcp_request_from_sdk(self, engine):
        """A genuine MCP request object built by the official SDK round-trips."""
        params = mcp_types.CallToolRequestParams(name="search", arguments={"q": "hi"})
        real = mcp_types.JSONRPCRequest(
            jsonrpc="2.0", id=1, method="tools/call",
            params=params.model_dump(exclude_none=True),
        )
        result = engine.translate(real.model_dump(exclude_none=True),
                                  TranslationDirection.MCP_TO_A2A.value)
        assert result.success
        a2a_types.Task.model_validate(result.target_data["task"])
