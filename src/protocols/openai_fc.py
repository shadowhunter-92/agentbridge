"""OpenAI function-calling adapter (the de-facto tool-call format most LLM agents speak).

Request wire = an OpenAI tool call: {id, type:"function", function:{name, arguments(JSON str)}}.
Result wire  = an OpenAI tool result message: {role:"tool", tool_call_id, content}.
"""

import json
from typing import Any, Dict

from .base import ProtocolAdapter
from .canonical import CanonicalCall, CanonicalResult


class OpenAIFunctionAdapter(ProtocolAdapter):
    name = "openai"

    def to_canonical_call(self, wire: Dict[str, Any]) -> CanonicalCall:
        fn = wire.get("function", {}) or {}
        raw_args = fn.get("arguments", "{}")
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            arguments = {}
        kwargs = dict(capability=fn.get("name", ""), arguments=arguments,
                      source_protocol=self.name)
        if wire.get("id"):
            kwargs["call_id"] = str(wire["id"])
        return CanonicalCall(**kwargs)

    def from_canonical_call(self, call: CanonicalCall) -> Dict[str, Any]:
        # Conforms to openai.types.chat ChatCompletionMessageToolCall (arguments is a JSON string).
        return {
            "id": call.call_id,
            "type": "function",
            "function": {"name": call.capability, "arguments": json.dumps(call.arguments)},
        }

    def to_canonical_result(self, wire: Dict[str, Any]) -> CanonicalResult:
        content = wire.get("content", "") if isinstance(wire, dict) else ""
        return CanonicalResult.from_text(content if isinstance(content, str) else str(content))

    def from_canonical_result(self, result: CanonicalResult) -> Dict[str, Any]:
        # OpenAI tool-result message shape.
        return {"role": "tool", "tool_call_id": result.metadata.get("tool_call_id", ""),
                "content": result.text()}
