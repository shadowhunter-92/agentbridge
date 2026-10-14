"""Hash-linked audit records with explicit trust and retention limits.

Durable stores serialize chained appends across workers. A self-consistent chain
detects edits within its retained history; it is not WORM storage or independent
proof of a destination effect. A signed checkpoint authenticates its signer's
statement, not independent custody or authorization to delete history.

Production truncation remains disabled pending qualified external anchoring.
Controlled nonproduction truncation checks local and durable legal holds and
requires the retained suffix to be interpreted against preserved checkpoints.
Use AuditTrustStore for cross-process holds; an in-memory flag is process-local.
"""

import hashlib
import json
import os
import threading
from contextlib import nullcontext
from dataclasses import asdict, dataclass
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
        self._legal_hold = False
        # SQL remains authoritative. Do not eagerly duplicate all historical
        # evidence in every worker; explicit verification/export loads it.
        self._entries: List[AuditEntry] = ([
            AuditEntry(**rec) for rec in self.store.load_audit()
        ] if isinstance(self.store, InMemoryStore) else [])

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

        # Durable stores serialize the chain themselves. An extra audit lock
        # would invert the store -> component order of an outer SQL transaction.
        guard = self._lock if isinstance(self.store, InMemoryStore) else nullcontext()
        with guard:
            rec = self.store.append_audit_chained(build)
            entry = AuditEntry(**rec)
            if isinstance(self.store, InMemoryStore):
                self._entries.append(entry)
            return entry

    def entries(self) -> List[AuditEntry]:
        if isinstance(self.store, InMemoryStore):
            return list(self._entries)
        return [AuditEntry(**rec) for rec in self.store.load_audit()]

    def count(self) -> int:
        """Persisted count without transferring/deserializing historical records.

        PostgreSQL COUNT observes MVCC rows and is not claimed to be O(1).
        """
        return self.store.audit_count()

    def export_jsonl(self) -> str:
        """Audit export for compliance (one JSON object per line)."""
        return "\n".join(json.dumps(asdict(e), sort_keys=True) for e in self.entries())

    def verify_integrity(self) -> bool:
        """True iff this process's in-memory view of the chain is intact. Auto-detects a
        retention-truncated chain (legitimately starting at seq>0) and verifies its internal
        integrity — pair with a signed checkpoint to prove the truncation point."""
        if not isinstance(self.store, InMemoryStore):
            return self.verify_durable()
        records = [asdict(e) for e in self._entries]
        return self.verify_chain(records, require_genesis=self._starts_at_genesis(records))

    def verify_durable(self) -> bool:
        """Load the full chain from the store and verify it — the true cross-worker check.
        Like verify_integrity, tolerates a retention-truncated chain."""
        records = self.store.load_audit()
        if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
            # Destructive retention is disabled for production until durable
            # checkpoint anchoring is implemented and independently trusted.
            # Never mistake a self-consistent suffix for intact full history.
            return self.verify_chain(records, require_genesis=True)
        return self.verify_chain(records, require_genesis=self._starts_at_genesis(records))

    @staticmethod
    def _starts_at_genesis(records: List[Dict[str, Any]]) -> bool:
        return not records or min(r["seq"] for r in records) == 0

    @staticmethod
    def verify_chain(records: List[Dict[str, Any]], require_genesis: bool = True) -> bool:
        """Verify audit-entry dicts: contiguous seqs, intact hash links, and each entry_hash
        recomputes (detects fork, reorder, edit, or deletion).

        require_genesis=True (default): the chain must be COMPLETE from seq 0 (prev=GENESIS).
        require_genesis=False: verify INTERNAL integrity only, anchored at the earliest entry's
        prev_hash — for a retention-truncated chain that legitimately starts at seq>0. (A signed
        checkpoint, not this function, vouches that the truncation point itself was authorized.)"""
        ordered = sorted(records, key=lambda r: r["seq"])
        if not ordered:
            return True
        if require_genesis and (ordered[0]["seq"] != 0 or ordered[0]["prev_hash"] != AuditLog.GENESIS):
            return False
        prev_hash = ordered[0]["prev_hash"]      # GENESIS for a full chain; the pre-truncation head otherwise
        prev_seq = ordered[0]["seq"] - 1
        for rec in ordered:
            if rec["seq"] != prev_seq + 1 or rec["prev_hash"] != prev_hash:
                return False
            fields = {k: rec[k] for k in AuditEntry.__dataclass_fields__ if k in rec}
            if AuditEntry(**fields).compute_hash() != rec["entry_hash"]:
                return False
            prev_hash = rec["entry_hash"]
            prev_seq = rec["seq"]
        return True

    # --- signed checkpoints (compliance / third-party verifiable) ---------------------
    def head_hash(self) -> str:
        """The current chain head hash (GENESIS if empty)."""
        head = self.store.load_audit_head()
        return head["entry_hash"] if head else self.GENESIS

    @staticmethod
    def _checkpoint_payload(seq: int, head_hash: str) -> bytes:
        return f"agentbridge-audit-checkpoint:{seq}:{head_hash}".encode()

    def checkpoint(self, sign, public_key_hex: str) -> Dict[str, Any]:
        """Sign the current audit head so a third party can later prove the log was not
        truncated or rewound past this point. `sign(bytes) -> bytes` is an Ed25519 signer
        (e.g. AgentIdentity.sign for an operator key)."""
        record = self.store.load_audit_head()
        seq = record["seq"] + 1 if record else 0
        head = record["entry_hash"] if record else self.GENESIS
        sig = sign(self._checkpoint_payload(seq, head))
        return {"seq": seq, "head_hash": head, "algo": "ed25519",
                "public_key_hex": public_key_hex, "signature_hex": sig.hex(),
                "created_at": _now()}

    @staticmethod
    def verify_checkpoint(checkpoint: Dict[str, Any]) -> bool:
        """Verify a signed checkpoint's Ed25519 signature over (seq, head_hash)."""
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(checkpoint["public_key_hex"]))
            payload = AuditLog._checkpoint_payload(checkpoint["seq"], checkpoint["head_hash"])
            pub.verify(bytes.fromhex(checkpoint["signature_hex"]), payload)
            return True
        except (InvalidSignature, KeyError, ValueError):
            return False

    # --- retention / legal hold --------------------------------------------------
    def set_legal_hold(self, on: bool) -> None:
        """When True, truncate_before() refuses to delete anything. Use during
        investigations or litigation holds. Toggle-able by an operator."""
        with self._lock:
            self._legal_hold = bool(on)

    def is_legal_hold(self) -> bool:
        return self._legal_hold

    def truncate_before(self, seq: int) -> int:
        """Delete entries with seq < `seq` from the durable store and the in-memory cache.

        Returns the number of entries deleted. Refuses (returns 0) if a legal hold is
        active. After truncation, the remaining chain is still internally consistent:
        the first remaining entry's `prev_hash` references the (now-deleted) prior head,
        which is exactly what signed checkpoints preserve — anyone holding a checkpoint
        for seq=N can verify the chain was intact at N, and the live chain verifies from
        N forward (with the understanding that pre-N history lives only in the checkpoint
        signature, not in the live log).
        """
        if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
            # Reject direct library deletion as well as the disabled HTTP route.
            # A process-local legal hold is NOT sufficient for production.
            raise PermissionError("production audit deletion requires durable legal holds and trusted checkpoints")
        if seq <= 0:
            return 0
        with self._lock:
            if self._legal_hold:
                return 0
            removed = self.store.truncate_audit_before(seq)
            if removed > 0:
                self._entries = [e for e in self._entries if e.seq >= seq]
            return removed
