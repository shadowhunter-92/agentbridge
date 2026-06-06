"""Google Gemini function-calling adapter (google-genai).

Request wire = a Gemini FunctionCall: {name, args(dict)}.
Result wire  = a Gemini FunctionResponse: {name, response(dict)}.
Unlike OpenAI, Gemini `args` is a real object, not a JSON string.
"""

from typing import Any, Dict

from .base import ProtocolAdapter
from .canonical import CanonicalCall, CanonicalResult


class GeminiFunctionAdapter(ProtocolAdapter):
    name = "gemini"

    def to_canonical_call(self, wire: Dict[str, Any]) -> CanonicalCall:
        kwargs = dict(capability=wire.get("name", ""),
                      arguments=wire.get("args", {}) or {},
                      source_protocol=self.name)
        if wire.get("id"):
            kwargs["call_id"] = str(wire["id"])
        return CanonicalCall(**kwargs)

    def from_canonical_call(self, call: CanonicalCall) -> Dict[str, Any]:
        # Conforms to google.genai.types.FunctionCall.
        return {"name": call.capability, "args": call.arguments}

    def to_canonical_result(self, wire: Dict[str, Any]) -> CanonicalResult:
        response = wire.get("response", {}) if isinstance(wire, dict) else {}
        text = response.get("result") or response.get("content") or ""
        return CanonicalResult.from_text(str(text))

    def from_canonical_result(self, result: CanonicalResult) -> Dict[str, Any]:
        # Conforms to google.genai.types.FunctionResponse.
        return {"name": result.metadata.get("name", "result"),
                "response": {"result": result.text()}}
