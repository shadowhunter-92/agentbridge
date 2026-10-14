"""Unsupported protocol procedures never reach live target transport."""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from src.proxy.inline_proxy import InlineProxy


@pytest.mark.parametrize("method", ["resources/read", "prompts/get", "tools/list", "notifications/cancelled", "sampling/createMessage"])
def test_mcp_unsupported_procedures_do_not_dispatch(method):
    with patch("src.proxy.transport.send_a2a_message", new_callable=AsyncMock) as invoke:
        with pytest.raises(ValueError, match="only tools/call"):
            asyncio.run(InlineProxy().mcp_request_to_a2a_agent({"method":method,"params":{"name":"delete_all","arguments":{}}}, "https://example.invalid"))
        invoke.assert_not_awaited()


@pytest.mark.parametrize("method,state", [("tasks/get","submitted"),("tasks/cancel","submitted"),("tasks/resubscribe","submitted"),("tasks/send","working"),("tasks/send","completed")])
def test_a2a_lifecycle_never_dispatches(method,state):
    wire={"jsonrpc":"2.0","id":"one","method":method,"params":{"task":{
        "kind":"task","status":{"state":state},"history":[{"parts":[{"kind":"data","data":{"name":"delete_all","arguments":{}}}]}]}}}
    with patch("src.proxy.transport.call_mcp_tool",new_callable=AsyncMock) as invoke:
        with pytest.raises(ValueError):
            asyncio.run(InlineProxy().a2a_request_to_mcp_agent(wire,"python",[]))
        invoke.assert_not_awaited()


def test_bare_unknown_actions_are_denied_before_dispatch():
    with patch("src.proxy.transport.call_mcp_tool",new_callable=AsyncMock) as invoke:
        with pytest.raises(ValueError,match="lacks explicit tool capability"):
            asyncio.run(InlineProxy().a2a_request_to_mcp_agent(
                {"method":"tasks/send","params":{"task":{"status":{"state":"submitted"},"history":[]}}},"python",[]))
        invoke.assert_not_awaited()


def test_valid_supported_a2a_action_still_dispatches():
    wire={"jsonrpc":"2.0","id":"one","method":"tasks/send","params":{"task":{
        "kind":"task","status":{"state":"submitted"},"history":[{"parts":[{"kind":"data","data":{"name":"add","arguments":{"a":2,"b":3}}}]}]}}}
    with patch("src.proxy.transport.call_mcp_tool",new_callable=AsyncMock,return_value={"raw":["5"],"isError":False}) as invoke:
        out=asyncio.run(InlineProxy().a2a_request_to_mcp_agent(wire,"python",[]))
        assert out["tool"]=="add"
        assert out["a2a_message"]["parts"][0]["text"]=="5"
        invoke.assert_awaited_once()
