import httpx
import pytest

from src.governance.identity import AgentIdentity
from src.serve.tenant_agent_client import TenantAgentClient
from tests.test_authority import authority as authority
from tests.test_tenant_http import http_app as http_app
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


@pytest.mark.asyncio
async def test_client_routes_and_inspects_operation_over_real_http(tenant_app, http_app, loopback_server):
    with loopback_server(lambda _: http_app) as (url, _):
        async with TenantAgentClient(url, "alpha", tenant_app[2]["alpha"], allow_loopback_http=True) as client:
            result = await client.route(
                "mcp",
                "mcp",
                {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
                operation_id="sdk-tenant-operation-12345",
            )
            assert "translated_wire" in result
            assert (await client.operation("sdk-tenant-operation-12345"))["state"] == "succeeded"
            with pytest.raises(httpx.HTTPStatusError) as denied:
                await client.route(
                    "mcp",
                    "mcp",
                    {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
                    operation_id="sdk-tenant-operation-12345",
                )
            assert denied.value.response.status_code == 409
        async with TenantAgentClient(url, "beta", tenant_app[2]["beta"], allow_loopback_http=True) as client:
            with pytest.raises(httpx.HTTPStatusError) as denied:
                await client.operation("sdk-tenant-operation-12345")
            assert denied.value.response.status_code == 403


@pytest.mark.parametrize(
    "url",
    [
        "http://destination.example.org",
        "https://user:password@destination.example.org",
        "https://destination.example.org/path",
        "https://destination.example.org?key=secret",
    ],
)
def test_client_rejects_untrusted_origin_configuration(url):
    with pytest.raises(ValueError, match="HTTPS origin"):
        TenantAgentClient(url, "alpha", AgentIdentity.generate("worker"), allow_loopback_http=True)
