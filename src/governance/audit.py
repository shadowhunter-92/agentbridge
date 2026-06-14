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
        # The seq + prev_hash come from the DURABLE head inside the store's atomic section,
        # NOT from this process's in-memory view — so concurrent workers cannot fork the
        # chain (each gets a distinct, correctly-linked seq). See store.append_audit_chained.
        def build(seq: int, prev_hash: str) -> Dict[str, Any]:
            entry = AuditEntry(
                seq=seq, timestamp=_now(), actor=actor, action=action,
                source_protocol=source_protocol, target_protocol=target_protocol,
                capability=capability, decision=decision, reason=reason, cost=cost,
                prev_hash=prev_hash,
            )
            entry.entry_hash = entry.compute_hash()
            return asdict(entry)

        with self._lock:
            rec = self.store.append_audit_chained(build)
            entry = AuditEntry(**rec)
            self._entries.append(entry)        # local cache; the store is the source of truth
            return entry

    def entries(self) -> List[AuditEntry]:
        return list(self._entries)

    def export_jsonl(self) -> str:
        """Audit export for compliance (one JSON object per line)."""
        return "\n".join(json.dumps(asdict(e), sort_keys=True) for e in self._entries)

    def verify_integrity(self) -> bool:
        """True iff this process's in-memory view of the chain is intact."""
        return self.verify_chain([asdict(e) for e in self._entries])

    def verify_durable(self) -> bool:
        """Load the full chain from the store and verify it — the true cross-worker check."""
        return self.verify_chain(self.store.load_audit())

    @staticmethod
    def verify_chain(records: List[Dict[str, Any]]) -> bool:
        """Verify a list of audit-entry dicts: sequential seqs from 0, intact hash links, and
        each entry_hash matches a recompute (detects fork, reorder, edit, or deletion)."""
        prev = AuditLog.GENESIS
        for i, rec in enumerate(sorted(records, key=lambda r: r["seq"])):
            if rec["seq"] != i or rec["prev_hash"] != prev:
                return False
            fields = {k: rec[k] for k in AuditEntry.__dataclass_fields__ if k in rec}
            if AuditEntry(**fields).compute_hash() != rec["entry_hash"]:
                return False
            prev = rec["entry_hash"]
        return True

    # --- signed checkpoints (compliance / third-party verifiable) ---------------------
    def head_hash(self) -> str:
        """The current chain head hash (GENESIS if empty)."""
        with self._lock:
            return self._entries[-1].entry_hash if self._entries else self.GENESIS

    @staticmethod
    def _checkpoint_payload(seq: int, head_hash: str) -> bytes:
        return f"agentbridge-audit-checkpoint:{seq}:{head_hash}".encode()

    def checkpoint(self, sign, public_key_hex: str) -> Dict[str, Any]:
        """Sign the current audit head so a third party can later prove the log was not
        truncated or rewound past this point. `sign(bytes) -> bytes` is an Ed25519 signer
        (e.g. AgentIdentity.sign for an operator key)."""
        with self._lock:
            seq = len(self._entries)
            head = self._entries[-1].entry_hash if self._entries else self.GENESIS
        sig = sign(self._checkpoint_payload(seq, head))
        return {"seq": seq, "head_hash": head, "algo": "ed25519",
                "public_key_hex": public_key_hex, "signature_hex": sig.hex(),
                "created_at": _now()}

    @staticmethod
    def verify_checkpoint(checkpoint: Dict[str, Any]) -> bool:
        """Verify a signed checkpoint's Ed25519 signature over (seq, head_hash)."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(checkpoint["public_key_hex"]))
            payload = AuditLog._checkpoint_payload(checkpoint["seq"], checkpoint["head_hash"])
            pub.verify(bytes.fromhex(checkpoint["signature_hex"]), payload)
            return True
        except (InvalidSignature, KeyError, ValueError):
            return False
