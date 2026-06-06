"""
N-protocol conformance + any-to-any translation tests.

Same rigor we applied to MCP and A2A, now for every protocol in the registry:
each adapter's rendered wire form is validated against the protocol's REAL official
SDK type, and we prove any-protocol -> any-protocol translation preserves intent.

Protocols covered: mcp, a2a, acp, openai.
"""

import json
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("redis", MagicMock())
sys.modules.setdefault("redis.asyncio", MagicMock())

from src.protocols import default_registry as reg
from src.protocols.canonical import CanonicalCall, CanonicalResult


def _call(cap="add", args=None):
    return CanonicalCall(capability=cap, arguments=args or {"a": 2, "b": 3}, call_id="c-1")


# --------------------------------------------------------------------------------------
# Per-protocol conformance: rendered wire validates against the REAL official SDK type.
# --------------------------------------------------------------------------------------

def test_mcp_render_conforms_to_official_type():
    mcp = pytest.importorskip("mcp.types")
    wire = reg.get("mcp").from_canonical_call(_call())
    params = mcp.CallToolRequestParams.model_validate(wire["params"])
    assert params.name == "add"
    assert params.arguments == {"a": 2, "b": 3}


def test_a2a_render_conforms_to_official_type():
    a2a = pytest.importorskip("a2a.types")
    wire = reg.get("a2a").from_canonical_call(_call())
    task = a2a.Task.model_validate(wire)
    assert task.history and task.context_id


def test_acp_render_conforms_to_official_type():
    acp = pytest.importorskip("acp_sdk.models")
    wire = reg.get("acp").from_canonical_call(_call())
    # The run-create input carries real ACP Messages.
    msg = acp.Message.model_validate(wire["input"][0])
    assert msg.role == "user"
    assert msg.parts


def test_openai_render_conforms_to_official_type():
    oa = pytest.importorskip("openai.types.chat")
    wire = reg.get("openai").from_canonical_call(_call())
    tc = oa.ChatCompletionMessageToolCall.model_validate(wire)
    assert tc.function.name == "add"
    assert json.loads(tc.function.arguments) == {"a": 2, "b": 3}


def test_acp_result_conforms_to_official_type():
    acp = pytest.importorskip("acp_sdk.models")
    wire = reg.get("acp").from_canonical_result(CanonicalResult.from_text("5"))
    msg = acp.Message.model_validate(wire)
    assert msg.parts[0].content == "5"


def test_gemini_render_conforms_to_official_type():
    gt = pytest.importorskip("google.genai.types")
    wire = reg.get("gemini").from_canonical_call(_call())
    fc = gt.FunctionCall.model_validate(wire)
    assert fc.name == "add"
    assert fc.args == {"a": 2, "b": 3}


def test_agntcy_render_conforms_to_official_type():
    am = pytest.importorskip("agntcy_acp.models")
    wire = reg.get("agntcy").from_canonical_call(_call())
    # The run-create request validates against the REAL AGNTCY type,
    # and the message content validates as a real MessageTextBlock.
    am.RunCreateStateless.model_validate(wire)
    block = wire["input"]["messages"][0]["content"]
    am.MessageTextBlock.model_validate(block)
    assert block["text"]


# --------------------------------------------------------------------------------------
# Any-to-any: translate a call from every protocol to every other; intent survives.
# --------------------------------------------------------------------------------------

PROTOCOLS = ["mcp", "a2a", "acp", "openai", "gemini", "agntcy"]


@pytest.mark.parametrize("src", PROTOCOLS)
@pytest.mark.parametrize("dst", PROTOCOLS)
def test_any_to_any_call_preserves_intent(src, dst):
    # Start from a canonical call, render to the SOURCE wire, then translate src->dst,
    # then decode the DEST wire back to canonical and check capability + arguments held.
    src_wire = reg.get(src).from_canonical_call(_call("add", {"a": 2, "b": 3}))
    dst_wire = reg.translate_call(src_wire, src, dst)
    decoded = reg.get(dst).to_canonical_call(dst_wire)
    assert decoded.capability == "add"
    assert decoded.arguments == {"a": 2, "b": 3}


def test_registry_lists_all_protocols():
    assert reg.protocols() == ["a2a", "acp", "agntcy", "gemini", "mcp", "openai"]
