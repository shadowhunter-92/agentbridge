"""
Tamper-evident audit log.

Every governed call appends an entry whose hash chains to the previous entry's hash
(like a mini blockchain). Any later edit/deletion breaks the chain, which
`verify_integrity()` detects. This is the "audit trail" enterprises pay for.
"""

import hashlib
import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .store import GovernanceStore, InMemoryStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuditEntry:
    seq: int
    timestamp: str
    actor: str                  # agent_id of the caller
    action: str                 # e.g. "route_call"
    source_protocol: str
    target_protocol: str
    capability: str
    decision: str               # "allow" | "deny"
    reason: str
    cost: float
    prev_hash: str
    entry_hash: str = ""

    def _payload(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("entry_hash", None)
        return d

    def compute_hash(self) -> str:
        blob = json.dumps(self._payload(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()


class AuditLog:
    GENESIS = "0" * 64

    def __init__(self, store: Optional[GovernanceStore] = None):
        self.store = store or InMemoryStore()
        self._lock = threading.RLock()
        self._entries: List[AuditEntry] = [
            AuditEntry(**rec) for rec in self.store.load_audit()
        ]

    def record(self, *, actor: str, action: str, source_protocol: str,
               target_protocol: str, capability: str, decision: str,
               reason: str = "", cost: float = 0.0) -> AuditEntry:
        with self._lock:
            prev_hash = self._entries[-1].entry_hash if self._entries else self.GENESIS
            entry = AuditEntry(
                seq=len(self._entries),
                timestamp=_now(),
                actor=actor,
                action=action,
                source_protocol=source_protocol,
                target_protocol=target_protocol,
                capability=capability,
                decision=decision,
                reason=reason,
                cost=cost,
                prev_hash=prev_hash,
            )
            entry.entry_hash = entry.compute_hash()
            self._entries.append(entry)
            self.store.append_audit(asdict(entry))
            return entry

    def entries(self) -> List[AuditEntry]:
        return list(self._entries)

    def export_jsonl(self) -> str:
        """Audit export for compliance (one JSON object per line)."""
        return "\n".join(json.dumps(asdict(e), sort_keys=True) for e in self._entries)

    def verify_integrity(self) -> bool:
        """True iff the chain is intact (no entry altered, removed, or reordered)."""
        prev = self.GENESIS
        for i, entry in enumerate(self._entries):
            if entry.seq != i:
                return False
            if entry.prev_hash != prev:
                return False
            if entry.entry_hash != entry.compute_hash():
                return False
            prev = entry.entry_hash
        return True
