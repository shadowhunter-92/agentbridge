"""
Per-agent budgets: a spend cap and a rate cap (calls per rolling window).

Atomic reserve -> commit/release (fixes the deep-review TOCTOU race): the gateway
RESERVES budget before invoking a target, then COMMITS on success or RELEASES on
failure. Concurrent calls can't both slip past the cap because reserve() holds a lock
and counts reserved-but-not-committed spend.

Store-backed so spend survives restarts.
"""

import threading
import time
import uuid
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from .store import GovernanceStore, InMemoryStore


class Budget:
    def __init__(self, spend_limit: float = 100.0, rate_limit: int = 1000,
                 window_seconds: int = 3600, spent: float = 0.0,
                 calls: Optional[List[float]] = None):
        self.spend_limit = spend_limit
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self.spent = spent
        # Sorted-by-insertion timestamps of recent calls within the rate window.
        # A deque lets us drop expired calls from the left in amortized O(1),
        # instead of rebuilding the whole list on every call (was O(n) per call
        # -> O(n^2) under load; see tools/benchmark.py).
        self._calls: Deque[float] = deque(calls or [])
        self._reserved: Dict[str, float] = {}
        self._lock = threading.RLock()

    # --- introspection ---
    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        calls = self._calls
        while calls and calls[0] <= cutoff:
            calls.popleft()

    @property
    def reserved(self) -> float:
        return sum(self._reserved.values())

    def remaining(self) -> float:
        return self.spend_limit - self.spent - self.reserved

    def can_afford(self, cost: float, now: Optional[float] = None) -> Tuple[bool, str]:
        with self._lock:
            now = now if now is not None else time.time()
            self._prune(now)
            if self.spent + self.reserved + cost > self.spend_limit:
                return False, f"spend cap exceeded ({self.spent}+{self.reserved}+{cost} > {self.spend_limit})"
            if len(self._calls) + len(self._reserved) >= self.rate_limit:
                return False, f"rate cap exceeded (>= {self.rate_limit} in window)"
            return True, "ok"

    # --- atomic reserve / commit / release ---
    def reserve(self, cost: float, now: Optional[float] = None) -> Tuple[Optional[str], str]:
        with self._lock:
            ok, why = self.can_afford(cost, now)
            if not ok:
                return None, why
            token = uuid.uuid4().hex
            self._reserved[token] = cost
            return token, "reserved"

    def commit(self, token: str, now: Optional[float] = None) -> bool:
        with self._lock:
            if token not in self._reserved:
                return False
            cost = self._reserved.pop(token)
            self.spent += cost
            self._calls.append(now if now is not None else time.time())
            return True

    def release(self, token: str) -> bool:
        with self._lock:
            return self._reserved.pop(token, None) is not None

    # backward-compatible direct charge (non-reserved path)
    def charge(self, cost: float, now: Optional[float] = None) -> None:
        with self._lock:
            self.spent += cost
            self._calls.append(now if now is not None else time.time())

    def state(self) -> Dict:
        with self._lock:
            return {"spend_limit": self.spend_limit, "rate_limit": self.rate_limit,
                    "window_seconds": self.window_seconds, "spent": self.spent,
                    "calls": list(self._calls)}

    @classmethod
    def from_state(cls, s: Dict) -> "Budget":
        return cls(spend_limit=s["spend_limit"], rate_limit=s["rate_limit"],
                   window_seconds=s["window_seconds"], spent=s.get("spent", 0.0),
                   calls=s.get("calls", []))


class BudgetManager:
    def __init__(self, store: Optional[GovernanceStore] = None, default_factory=None):
        self.store = store or InMemoryStore()
        self._budgets: Dict[str, Budget] = {}
        self._default_factory = default_factory or (lambda: Budget())
        self._lock = threading.RLock()

    def set_budget(self, agent_id: str, budget: Budget) -> None:
        with self._lock:
            self._budgets[agent_id] = budget
            self.store.upsert_budget(agent_id, budget.state())

    def get(self, agent_id: str) -> Budget:
        with self._lock:
            if agent_id in self._budgets:
                return self._budgets[agent_id]
            rec = self.store.get_budget(agent_id)
            budget = Budget.from_state(rec) if rec else self._default_factory()
            self._budgets[agent_id] = budget
            return budget

    def persist(self, agent_id: str) -> None:
        with self._lock:
            if agent_id in self._budgets:
                self.store.upsert_budget(agent_id, self._budgets[agent_id].state())
