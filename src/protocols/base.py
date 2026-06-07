"""
ProtocolAdapter: the contract each protocol implements to plug into the meta-bridge.

Four methods map a protocol's wire form to/from the canonical model. With this,
any protocol can talk to any other via canonical — no pairwise code.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from .canonical import CanonicalCall, CanonicalResult


class MalformedWireError(ValueError):
    """Raised when a wire payload cannot be parsed into the canonical model.

    Previously the adapters silently returned empty strings on malformed input,
    which turned a bad request into a confusing no-op downstream. They now fail
    loudly with a protocol-named, descriptive error.
    """


def require_mapping(wire: Any, proto_name: str, what: str = "request") -> Dict[str, Any]:
    """Guard: the wire for a request must be a JSON object (dict). Raise clearly if not."""
    if not isinstance(wire, dict):
        raise MalformedWireError(
            f"{proto_name}: expected a JSON object for the {what}, "
            f"got {type(wire).__name__}"
        )
    return wire


class ProtocolAdapter(ABC):
    #: short stable id, e.g. "mcp", "a2a", "acp", "openai"
    name: str = "base"

    @abstractmethod
    def to_canonical_call(self, wire: Dict[str, Any]) -> CanonicalCall:
        """Parse this protocol's request wire form into a CanonicalCall."""

    @abstractmethod
    def from_canonical_call(self, call: CanonicalCall) -> Dict[str, Any]:
        """Render a CanonicalCall into this protocol's request wire form."""

    @abstractmethod
    def to_canonical_result(self, wire: Dict[str, Any]) -> CanonicalResult:
        """Parse this protocol's response wire form into a CanonicalResult."""

    @abstractmethod
    def from_canonical_result(self, result: CanonicalResult) -> Dict[str, Any]:
        """Render a CanonicalResult into this protocol's response wire form."""
