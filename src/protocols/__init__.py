"""
N-protocol canonical layer (the meta-bridge hub).

Every protocol speaks to ONE canonical model (CanonicalCall / CanonicalResult),
so adding a protocol is O(1) adapters, not O(N) pairwise mappings. Any-to-any
translation goes: source wire -> canonical -> target wire.
"""

from .canonical import CanonicalCall, CanonicalResult
from .base import ProtocolAdapter, MalformedWireError, require_mapping
from .registry import ProtocolRegistry, default_registry

__all__ = [
    "CanonicalCall",
    "CanonicalResult",
    "ProtocolAdapter",
    "MalformedWireError",
    "require_mapping",
    "ProtocolRegistry",
    "default_registry",
]
