"""AGNTCY Agent Connect Protocol adapter (Cisco AGNTCY / agntcy-acp).

A distinct protocol from IBM's ACP. Requests are run-creates over a LangGraph-style
input; messages carry `role` + `content`. We encode a tool-call as a JSON `content`
string so structured arguments survive, plus a text form for prose agents.

Request wire = {agent_id, input:{messages:[{role, content}]}}.
Result wire  = {role, content} (a Message).
"""

import json
from typing import Any, Dict, List

from .base import ProtocolAdapter
from .canonical import CanonicalCall, CanonicalResult


class AgntcyAcpAdapter(ProtocolAdapter):
    name = "agntcy"

    def _messages(self, wire: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(wire, dict):
            return []
        inp = wire.get("input", {})
        if isinstance(inp, dict) and "messages" in inp:
            return inp["messages"]
        if "messages" in wire:
            return wire["messages"]
        if "role" in wire:  # a bare Message
            return [wire]
        return []

    @staticmethod
    def _text_of(content: Any) -> str:
        # content is a MessageTextBlock dict {"type":"text","text":...} (or a bare str).
        if isinstance(content, dict):
            return content.get("text", "")
        return content if isinstance(content, str) else ""

    def to_canonical_call(self, wire: Dict[str, Any]) -> CanonicalCall:
        capability = wire.get("agent_id", "") if isinstance(wire, dict) else ""
        arguments, text = {}, None
        for msg in self._messages(wire):
            raw = self._text_of(msg.get("content"))
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "name" in data:
                    capability = data.get("name", capability)
                    arguments = data.get("arguments", arguments)
                    continue
            except Exception:
                pass
            if raw and text is None:
                text = raw
        return CanonicalCall(capability=capability, arguments=arguments, text=text,
                             source_protocol=self.name)

    def from_canonical_call(self, call: CanonicalCall) -> Dict[str, Any]:
        # input.messages carry agntcy Messages whose content is a MessageTextBlock.
        block = {"type": "text",
                 "text": json.dumps({"name": call.capability, "arguments": call.arguments})}
        message = {"role": "user", "content": block}
        return {"agent_id": call.capability or "agent", "input": {"messages": [message]}}

    def to_canonical_result(self, wire: Dict[str, Any]) -> CanonicalResult:
        msgs = self._messages(wire) or ([wire] if isinstance(wire, dict) and "content" in wire else [])
        texts = [self._text_of(m.get("content")) for m in msgs]
        return CanonicalResult.from_text(" ".join(t for t in texts if t))

    def from_canonical_result(self, result: CanonicalResult) -> Dict[str, Any]:
        return {"role": "assistant",
                "content": {"type": "text", "text": result.text()}}
