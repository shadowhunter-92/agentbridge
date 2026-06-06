"""
ProtocolAdapter: the contract each protocol implements to plug into the meta-bridge.

Four methods map a protocol's wire form to/from the canonical model. With this,
any protocol can talk to any other via canonical — no pairwise code.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from .canonical import CanonicalCall, CanonicalResult


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
