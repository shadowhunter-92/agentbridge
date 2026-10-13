"""Default-deny outbound execution for standalone MCP gateway tools."""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from src.serve.mcp_gateway import bridge_call_a2a, bridge_call_acp


def test_missing_operator_allowlist_denies_without_network(monkeypatch):
    monkeypatch.delenv("AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON", raising=False)
    monkeypatch.setenv("AGENTBRIDGE_EGRESS_PROXY_URL", "http://proxy:3128")
    with patch("src.proxy.transport.send_a2a_message", new_callable=AsyncMock) as remote:
        with pytest.raises(ValueError, match="not operator allowlisted"):
            asyncio.run(bridge_call_a2a("https://untrusted.example", "hi"))
        remote.assert_not_awaited()


@pytest.mark.parametrize("url", [
    "http://allowed.example", "https://allowed.example:8443",
    "https://admin:pass@allowed.example", "https://allowed.example/path",
    "https://allowed.example?query=1", "https://allowed.example/#fragment",
    "https://allowed.example.evil", "https://localhost", "https://127.0.0.1",
])
def test_untrusted_or_unsafe_remote_url_never_dispatches(monkeypatch, url):
    monkeypatch.setenv("AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON", '["https://allowed.example"]')
    monkeypatch.setenv("AGENTBRIDGE_EGRESS_PROXY_URL", "http://proxy:3128")
    with patch("src.proxy.transport.send_a2a_message", new_callable=AsyncMock) as remote:
        with pytest.raises(ValueError):
            asyncio.run(bridge_call_a2a(url, "hi"))
        remote.assert_not_awaited()


def test_missing_egress_proxy_denies_even_allowlisted(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON", '["https://allowed.example"]')
    monkeypatch.delenv("AGENTBRIDGE_EGRESS_PROXY_URL", raising=False)
    with patch("src.proxy.transport.call_acp_agent", new_callable=AsyncMock) as remote:
        with pytest.raises(ValueError, match="egress proxy"):
            asyncio.run(bridge_call_acp("https://allowed.example", "agent", "hi"))
        remote.assert_not_awaited()


def test_allowlisted_target_uses_operator_proxy(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON", '["https://allowed.example"]')
    monkeypatch.setenv("AGENTBRIDGE_EGRESS_PROXY_URL", "http://proxy:3128")
    with patch("src.proxy.transport.send_a2a_message", new_callable=AsyncMock, return_value={"texts":["ok"]}) as remote:
        assert asyncio.run(bridge_call_a2a("https://allowed.example", "hi")) == "ok"
        remote.assert_awaited_once_with("https://allowed.example", "hi", proxy_url="http://proxy:3128")
