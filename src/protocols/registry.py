"""
ProtocolRegistry — any-to-any translation via the canonical hub.

Register N adapters; translate between any pair without pairwise code:
    registry.translate_call(wire, "openai", "a2a")
    registry.translate_result(wire, "mcp", "acp")
"""

from typing import Any, Dict, List

from .base import ProtocolAdapter, MalformedWireError
from .mcp import McpAdapter
from .a2a import A2aAdapter
from .acp import AcpAdapter
from .openai_fc import OpenAIFunctionAdapter
from .gemini import GeminiFunctionAdapter
from .agntcy_acp import AgntcyAcpAdapter


class ProtocolRegistry:
    def __init__(self):
        self._adapters: Dict[str, ProtocolAdapter] = {}

    def register(self, adapter: ProtocolAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ProtocolAdapter:
        if name not in self._adapters:
            raise KeyError(f"Unknown protocol '{name}'. Known: {self.protocols()}")
        return self._adapters[name]

    def protocols(self) -> List[str]:
        return sorted(self._adapters)

    def translate_call(self, wire: Dict[str, Any], src: str, dst: str) -> Dict[str, Any]:
        canonical = self.get(src).to_canonical_call(wire)
        # Backstop: a structurally-valid but empty payload (e.g. {} or {"params": {}})
        # yields nothing to route. Fail loudly instead of forwarding an empty call.
        if not (canonical.capability or canonical.text or canonical.arguments):
            raise MalformedWireError(
                f"{src}: could not extract a capability, arguments, or text from the request"
            )
        return self.get(dst).from_canonical_call(canonical)

    def translate_result(self, wire: Dict[str, Any], src: str, dst: str) -> Dict[str, Any]:
        canonical = self.get(src).to_canonical_result(wire)
        return self.get(dst).from_canonical_result(canonical)


def _build_default() -> ProtocolRegistry:
    reg = ProtocolRegistry()
    for adapter in (McpAdapter(), A2aAdapter(), AcpAdapter(), OpenAIFunctionAdapter(),
                    GeminiFunctionAdapter(), AgntcyAcpAdapter()):
        reg.register(adapter)
    return reg


#: Ready-to-use registry with all built-in protocols.
default_registry = _build_default()
