"""
Input-validation tests for the protocol adapters + registry.

Before this, the adapters silently returned empty strings on malformed input,
turning a bad request into a confusing downstream no-op. They now raise a clear,
protocol-named MalformedWireError. These tests lock that behaviour in.
"""

import pytest

from src.protocols import default_registry as reg
from src.protocols import MalformedWireError, CanonicalCall


PROTOCOLS = ["mcp", "a2a", "acp", "openai", "gemini", "agntcy"]


@pytest.mark.parametrize("proto", PROTOCOLS)
@pytest.mark.parametrize("bad", [None, 42, "a string", ["a", "list"], 3.14, True])
def test_non_dict_request_raises_clearly(proto, bad):
    """A non-object request must raise MalformedWireError naming the protocol."""
    adapter = reg.get(proto)
    with pytest.raises(MalformedWireError) as exc:
        adapter.to_canonical_call(bad)
    assert proto in str(exc.value)


@pytest.mark.parametrize("proto", PROTOCOLS)
def test_empty_payload_is_rejected_by_registry(proto):
    """A structurally-valid but empty payload yields nothing to route -> raise."""
    with pytest.raises(MalformedWireError):
        reg.translate_call({}, proto, "mcp")


def test_registry_rejects_non_dict():
    with pytest.raises(MalformedWireError):
        reg.translate_call(None, "mcp", "a2a")


def test_mcp_missing_name_with_no_args_is_rejected():
    # tools/call with neither a name nor arguments is unroutable.
    with pytest.raises(MalformedWireError):
        reg.translate_call({"jsonrpc": "2.0", "id": "1", "method": "tools/call",
                            "params": {}}, "mcp", "a2a")


def test_valid_calls_still_translate_every_pair():
    """Sanity: real calls are unaffected by the new guards (no regressions)."""
    wire = reg.get("mcp").from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    for dst in PROTOCOLS:
        out = reg.translate_call(wire, "mcp", dst)
        assert isinstance(out, dict) and out  # non-empty dict produced


def test_text_only_call_is_allowed():
    """A call carrying only free text (no capability) is valid and must NOT raise."""
    a2a_text_task = {
        "id": "t1", "contextId": "c1", "kind": "task",
        "status": {"state": "submitted"},
        "history": [{"kind": "message", "messageId": "m1", "role": "user",
                     "parts": [{"kind": "text", "text": "just some prose"}]}],
    }
    out = reg.translate_call(a2a_text_task, "a2a", "openai")
    assert isinstance(out, dict)
