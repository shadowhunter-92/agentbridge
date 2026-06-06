"""
Human-in-the-loop approval queue.

Capabilities flagged as sensitive require an operator approval before a call is allowed.
The gateway creates a pending request and denies the call until an operator approves it;
once approved, the agent's retry goes through.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ApprovalRequest:
    id: str
    agent_id: str
    capability: str
    cost: float
    status: str = "pending"          # pending | approved | denied
    created_at: str = field(default_factory=_now)


class ApprovalQueue:
    def __init__(self):
        self._lock = threading.RLock()
        self._requests: Dict[str, ApprovalRequest] = {}
        self._sensitive: Set[str] = set()
        # agent_id -> set of capabilities currently approved (one-shot, consumed on use)
        self._granted: Dict[str, Set[str]] = {}

    def mark_sensitive(self, capability: str) -> None:
        with self._lock:
            self._sensitive.add(capability)

    def requires_approval(self, capability: str) -> bool:
        return capability in self._sensitive

    def request(self, agent_id: str, capability: str, cost: float) -> ApprovalRequest:
        with self._lock:
            req = ApprovalRequest(id=uuid.uuid4().hex, agent_id=agent_id,
                                  capability=capability, cost=cost)
            self._requests[req.id] = req
            return req

    def approve(self, request_id: str) -> bool:
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req.status != "pending":
                return False
            req.status = "approved"
            self._granted.setdefault(req.agent_id, set()).add(req.capability)
            return True

    def deny(self, request_id: str) -> bool:
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req.status != "pending":
                return False
            req.status = "denied"
            return True

    def is_granted(self, agent_id: str, capability: str) -> bool:
        with self._lock:
            return capability in self._granted.get(agent_id, set())

    def consume(self, agent_id: str, capability: str) -> None:
        with self._lock:
            self._granted.get(agent_id, set()).discard(capability)

    def pending(self) -> List[ApprovalRequest]:
        with self._lock:
            return [r for r in self._requests.values() if r.status == "pending"]

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._requests.get(request_id)
