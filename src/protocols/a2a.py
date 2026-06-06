"""A2A adapter (Google / Linux Foundation, JSON-RPC public spec)."""

import uuid
from typing import Any, Dict

from .base import ProtocolAdapter
from .canonical import CanonicalCall, CanonicalResult


def _gen(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class A2aAdapter(ProtocolAdapter):
    name = "a2a"

    def _messages(self, task: Dict[str, Any]):
        return task.get("history") or task.get("messages") or []

    def to_canonical_call(self, wire: Dict[str, Any]) -> CanonicalCall:
        # Accept either a raw task, or a JSON-RPC envelope {params:{task:{...}}}.
        task = wire
        if "params" in wire and isinstance(wire["params"], dict) and "task" in wire["params"]:
            task = wire["params"]["task"]
        capability, arguments, text = "", {}, None
        for msg in self._messages(task):
            for part in msg.get("parts", []):
                if part.get("kind") == "data":
                    data = part.get("data", {})
                    capability = data.get("name") or data.get("tool_name") or capability
                    arguments = data.get("arguments", arguments)
                elif part.get("kind") == "text" and text is None:
                    text = part.get("text")
        kwargs = dict(capability=capability, arguments=arguments, text=text,
                      source_protocol=self.name)
        if wire.get("id") is not None:
            kwargs["call_id"] = str(wire["id"])
        return CanonicalCall(**kwargs)

    def from_canonical_call(self, call: CanonicalCall) -> Dict[str, Any]:
        # Conforms to a2a.types Task (kind/history/contextId, message kind/messageId).
        parts = [{"kind": "text", "text": call.text or f"call: {call.capability}"}]
        if call.capability:
            parts.append({"kind": "data",
                          "data": {"name": call.capability, "arguments": call.arguments}})
        return {
            "id": call.call_id,
            "contextId": _gen("ctx"),
            "kind": "task",
            "status": {"state": "submitted"},
            "history": [{
                "kind": "message",
                "messageId": _gen("msg"),
                "role": "agent",
                "parts": parts,
            }],
            "metadata": {"source_protocol": call.source_protocol},
        }

    def to_canonical_result(self, wire: Dict[str, Any]) -> CanonicalResult:
        texts = []
        parts = wire.get("parts", []) if isinstance(wire, dict) else []
        for part in parts:
            if part.get("kind") == "text":
                texts.append(part.get("text", ""))
        return CanonicalResult.from_text(" ".join(texts))

    def from_canonical_result(self, result: CanonicalResult) -> Dict[str, Any]:
        # Conforms to a2a.types Message (kind:message/messageId/role/parts).
        return {
            "kind": "message",
            "messageId": _gen("msg"),
            "role": "agent",
            "parts": [{"kind": "text", "text": result.text()}],
        }
