"""ACP adapter (Agent Communication Protocol — IBM/BeeAI, Linux Foundation).

ACP is message/run based over REST. A request is a list of input Messages; a result
is a Run whose `output` is a list of agent Messages. Each MessagePart carries
`content` + `content_type`. We encode a tool-call as a JSON part so structured
arguments survive, plus a text part for prose-only agents.
"""

import json
from typing import Any, Dict

from .base import ProtocolAdapter, require_mapping
from .canonical import CanonicalCall, CanonicalResult


class AcpAdapter(ProtocolAdapter):
    name = "acp"

    def _iter_parts(self, msg: Dict[str, Any]):
        return msg.get("parts", []) if isinstance(msg, dict) else []

    def to_canonical_call(self, wire: Dict[str, Any]) -> CanonicalCall:
        require_mapping(wire, self.name)
        # Accept a single Message, or a run-create {agent_name, input:[Message,...]}.
        capability = wire.get("agent_name", "")
        messages = []
        if isinstance(wire, dict) and "input" in wire:
            messages = wire["input"]
        elif isinstance(wire, dict) and "parts" in wire:
            messages = [wire]
        arguments, text = {}, None
        for msg in messages:
            for part in self._iter_parts(msg):
                ctype = part.get("content_type", "")
                content = part.get("content", "")
                if ctype == "application/json":
                    try:
                        data = json.loads(content)
                        capability = data.get("name", capability)
                        arguments = data.get("arguments", arguments)
                    except Exception:
                        pass
                elif ctype.startswith("text/") and text is None:
                    text = content
        return CanonicalCall(capability=capability, arguments=arguments, text=text,
                             source_protocol=self.name)

    def from_canonical_call(self, call: CanonicalCall) -> Dict[str, Any]:
        # Conforms to acp_sdk.models Message; wrapped as a run-create input.
        parts = [{
            "content_type": "application/json",
            "content": json.dumps({"name": call.capability, "arguments": call.arguments}),
        }]
        if call.text:
            parts.append({"content_type": "text/plain", "content": call.text})
        message = {"role": "user", "parts": parts}
        return {"agent_name": call.capability or "agent", "input": [message]}

    def to_canonical_result(self, wire: Dict[str, Any]) -> CanonicalResult:
        # Accept a Run ({output:[Message,...]}) or a single Message.
        messages = []
        if isinstance(wire, dict) and "output" in wire:
            messages = wire["output"]
        elif isinstance(wire, dict) and "parts" in wire:
            messages = [wire]
        texts = []
        for msg in messages:
            for part in self._iter_parts(msg):
                if part.get("content_type", "").startswith("text/"):
                    texts.append(part.get("content", ""))
        return CanonicalResult.from_text(" ".join(texts))

    def from_canonical_result(self, result: CanonicalResult) -> Dict[str, Any]:
        # Conforms to acp_sdk.models Message (role + parts[content/content_type]).
        return {
            "role": "agent",
            "parts": [{"content_type": "text/plain", "content": result.text()}],
        }
