"""Official MCP Streamable HTTP sessions against a real read-only SDK server."""
import asyncio
import time

import httpx
import pytest

pytest.importorskip("mcp")
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.proxy.transport import call_mcp_http_tool


@pytest.fixture
def mcp_app():
    recorded = []

    def factory(url):
        server = FastMCP("read-only-conformance", json_response=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://127.0.0.1:*"]))

        @server.tool()
        def add(a: int, b: int) -> int:
            return a + b

        @server.tool()
        async def delay(seconds: float) -> str:
            await asyncio.sleep(seconds)
            return "read-only delay complete"

        sdk_app = server.streamable_http_app()

        class Record:
            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    recorded.append((scope["method"], dict(scope["headers"])))
                await sdk_app(scope, receive, send)
        return Record()

    return factory, recorded


@pytest.mark.asyncio
async def test_official_http_negotiation_tool_errors_and_session_cleanup(mcp_app, loopback_server):
    factory, recorded = mcp_app
    with loopback_server(factory) as (url, _):
        success = await call_mcp_http_tool(url + "/mcp", "add", {"a": 2, "b": 3})
        assert not success["isError"] and success["raw"] == ["5"]
        assert success["protocolVersion"] == "2025-11-25"
        missing = await call_mcp_http_tool(url + "/mcp", "absent-tool", {})
        assert missing["isError"]
        malformed = await call_mcp_http_tool(url + "/mcp", "add", {"a": "not-an-integer", "b": 3})
        assert malformed["isError"]
        assert any(method == "DELETE" and b"mcp-session-id" in headers for method, headers in recorded)
        assert any(headers.get(b"mcp-protocol-version") == b"2025-11-25" for _, headers in recorded)


@pytest.mark.asyncio
async def test_http_reference_server_denies_bad_origin_and_unknown_session(mcp_app, loopback_server):
    factory, _ = mcp_app
    with loopback_server(factory) as (url, _):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        async with httpx.AsyncClient(trust_env=False) as http:
            response = await http.post(url + "/mcp", json=body,
                headers={"Accept": "application/json, text/event-stream", "Origin": "https://untrusted.example"})
            assert response.status_code == 403
            response = await http.post(url + "/mcp", json=body,
                headers={"Accept": "application/json, text/event-stream", "Mcp-Session-Id": "unknown-session"})
            assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1, True, float("inf")])
async def test_http_client_rejects_unbounded_timeouts_before_connect(timeout):
    with pytest.raises(ValueError):
        await call_mcp_http_tool("https://operator.example/mcp", "add", {}, timeout=timeout)


@pytest.mark.asyncio
async def test_http_tool_has_total_deadline(mcp_app, loopback_server):
    factory, _ = mcp_app
    with loopback_server(factory) as (url, _):
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await call_mcp_http_tool(url + "/mcp", "delay", {"seconds": 5}, timeout=.2)
        assert time.monotonic() - started < 2
