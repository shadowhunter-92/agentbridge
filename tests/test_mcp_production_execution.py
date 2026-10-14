"""Standalone hosted MCP tools cannot bypass the production execution gate."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.serve.mcp_gateway import bridge_call_a2a, bridge_call_acp


@pytest.mark.parametrize("environment", ["prod", "production"])
@pytest.mark.parametrize("protocol", ["a2a", "acp"])
def test_generic_production_remote_tool_never_dispatches(monkeypatch, environment, protocol):
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    monkeypatch.setenv("AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON", '["https://allowed.example.org"]')
    monkeypatch.setenv("AGENTBRIDGE_EGRESS_PROXY_URL", "http://proxy.example.org:3128")
    name = "send_a2a_message" if protocol == "a2a" else "call_acp_agent"
    with patch("src.proxy.transport." + name, new_callable=AsyncMock, return_value={"texts": ["synthetic"]}) as remote:
        with pytest.raises(ValueError, match="destination-atomic"):
            if protocol == "a2a":
                asyncio.run(bridge_call_a2a("https://allowed.example.org", "synthetic"))
            else:
                asyncio.run(bridge_call_acp("https://allowed.example.org", "agent", "synthetic"))
        remote.assert_not_awaited()
