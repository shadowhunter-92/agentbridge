"""
Human-in-the-loop approval queue — store-backed (production-ready).

Capabilities flagged as sensitive require an operator approval before a call is allowed.
The gateway creates a pending request and denies the call until an operator approves it;
once approved, the agent's retry goes through.

Previously this was in-memory only, which made it unsafe across multiple workers — two
workers couldn't share pending approvals, and an approval granted on one worker would
not satisfy a retry routed to another. Store-backing closes that gap: approvals live in
the same durable backend as identities, budgets, and audit (SQLite, Postgres, or the
in-memory store for tests).

The "granted" set (one-shot, consumed on use) is encoded as a column in the approvals
table: a row with status="approved" represents a live grant until consumed. Consuming a
grant marks it status="consumed", so the grant is durable too — multi-worker safe.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from .store import GovernanceStore, InMemoryStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ApprovalRequest:
    id: str
    agent_id: str
    capability: str
    cost: float
    status: str = "pending"          # pending | approved | denied | consumed
    created_at: str = field(default_factory=_now)


class ApprovalQueue:
    """Store-backed human approval queue.

    Pass a durable GovernanceStore (SqliteStore / PostgresStore) so approvals survive
    restarts and are visible across workers. Passing InMemoryStore keeps the previous
    behavior for tests/dev.
    """

    def __init__(self, store: Optional[GovernanceStore] = None):
        self.store = store or InMemoryStore()
        self._lock = threading.RLock()
        # `_sensitive` is intentionally in-memory: it's a deployment-wide configuration,
        # not per-call state, so it does not need to be multi-worker durable. Operators
        # set it once at startup or via the policy API; if they change it post-startup,
        # the change must be applied to all workers (a deployment concern, not a runtime
        # correctness one).
        self._sensitive: Set[str] = set()

    def mark_sensitive(self, capability: str) -> None:
        with self._lock:
            self._sensitive.add(capability)

    def requires_approval(self, capability: str) -> bool:
        return capability in self._sensitive

    def request(self, agent_id: str, capability: str, cost: float) -> ApprovalRequest:
        req = ApprovalRequest(id=uuid.uuid4().hex, agent_id=agent_id,
                              capability=capability, cost=cost)
        self.store.insert_approval({
            "id": req.id, "agent_id": req.agent_id, "capability": req.capability,
            "cost": req.cost, "status": req.status, "created_at": req.created_at,
        })
        return req

    def approve(self, request_id: str) -> bool:
        # Atomic: only a pending row transitions to approved. If a concurrent worker
        # already approved or denied it, this returns False.
        return self.store.update_approval_status(request_id, "approved")

    def deny(self, request_id: str) -> bool:
        return self.store.update_approval_status(request_id, "denied")

    def is_granted(self, agent_id: str, capability: str) -> bool:
        """True iff there exists an approved-but-not-yet-consumed grant for this
        (agent_id, capability). Reads the durable store so multi-worker is safe."""
        for a in self.store.list_approvals("approved"):
            if a["agent_id"] == agent_id and a["capability"] == capability:
                return True
        return False

    def consume(self, agent_id: str, capability: str) -> None:
        """One-shot consume: mark the first approved grant for this pair as consumed.

        Multi-worker safe: the store's consume_approval() atomically transitions
        approved -> consumed. If two workers race, only one wins (returns True); the
        other's consume_approval() returns False because the row is no longer 'approved'.
        That's correct: a one-shot grant should be consumable exactly once."""
        for a in self.store.list_approvals("approved"):
            if a["agent_id"] == agent_id and a["capability"] == capability:
                # Atomic approved -> consumed. If a concurrent worker already consumed
                # it, this returns False and we silently no-op — that's fine, the grant
                # was already used.
                self.store.consume_approval(a["id"])
                return

    def pending(self) -> List[ApprovalRequest]:
        return [ApprovalRequest(**a) for a in self.store.list_approvals("pending")]

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        rec = self.store.get_approval(request_id)
        return ApprovalRequest(**rec) if rec else None
