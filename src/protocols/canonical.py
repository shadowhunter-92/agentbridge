"""
The canonical model every protocol maps to/from.

Kept intentionally small: an agent interaction is either an attempt to invoke a
capability (a tool/skill/function/agent) with arguments and/or free text, and a
result carrying text content plus an error flag.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class CanonicalCall:
    """A protocol-neutral request to invoke a capability."""
    capability: str                              # tool / skill / function / agent name
    arguments: Dict[str, Any] = field(default_factory=dict)
    text: Optional[str] = None                   # free-text form, if any
    call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    source_protocol: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def best_text(self) -> str:
        """A reasonable free-text rendering for protocols that take prose, not tool args."""
        if self.text:
            return self.text
        for key in ("text", "query", "prompt", "input", "message"):
            if key in self.arguments:
                return str(self.arguments[key])
        if self.arguments:
            return " ".join(f"{k}={v}" for k, v in self.arguments.items())
        return self.capability or ""


@dataclass
class CanonicalResult:
    """A protocol-neutral result of an invocation."""
    content: List[Dict[str, Any]] = field(default_factory=list)   # [{"type":"text","text":...}]
    is_error: bool = False
    result_id: str = field(default_factory=lambda: f"res_{uuid.uuid4().hex[:12]}")
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_text(cls, text: str, is_error: bool = False) -> "CanonicalResult":
        return cls(content=[{"type": "text", "text": text}], is_error=is_error)

    def text(self) -> str:
        return " ".join(
            block.get("text", "") for block in self.content if block.get("type") == "text"
        ).strip()
