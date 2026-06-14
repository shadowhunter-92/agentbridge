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


# --- pure helpers operating on a persisted budget-state dict --------------------------
# The durable state dict carries spend_limit, rate_limit, window_seconds, spent,
# calls[] and reserved{token: cost}. reserve/commit/release mutate it in place; running
# them INSIDE store.mutate_budget()'s atomic section is what makes them cross-worker safe
# (the old in-memory _reserved/_calls forked across processes -> double-spend).

def _prune(state: Dict, now: float) -> None:
    cutoff = now - state["window_seconds"]
    state["calls"] = [t for t in state.get("calls", []) if t > cutoff]


def _reserved_sum(state: Dict) -> float:
    return sum(state.get("reserved", {}).values())


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
            rec = self.store.get_budget(agent_id)
            if rec:
                budget = Budget.from_state(rec)
            elif agent_id in self._budgets:
                budget = self._budgets[agent_id]
            else:
                budget = self._default_factory()
            self._budgets[agent_id] = budget
            return budget

    def persist(self, agent_id: str) -> None:
        with self._lock:
            if agent_id in self._budgets:
                self.store.upsert_budget(agent_id, self._budgets[agent_id].state())

    def _seed(self, agent_id: str, state: Dict) -> Dict:
        """Fill an empty/partial persisted state with this agent's defaults."""
        if not state:
            with self._lock:
                base = self._budgets.get(agent_id)
            state.update((base.state() if base else self._default_factory().state()))
        state.setdefault("spent", 0.0)
        state.setdefault("calls", [])
        state.setdefault("reserved", {})
        return state

    # --- store-backed atomic operations (cross-worker safe) ---------------------------
    def can_afford(self, agent_id: str, cost: float,
                   now: Optional[float] = None) -> Tuple[bool, str]:
        now = now if now is not None else time.time()

        def mutator(state: Dict) -> Tuple[bool, str]:
            self._seed(agent_id, state)
            _prune(state, now)
            reserved = _reserved_sum(state)
            if state["spent"] + reserved + cost > state["spend_limit"]:
                return False, (f"spend cap exceeded ({state['spent']}+{reserved}+{cost} "
                               f"> {state['spend_limit']})")
            if len(state["calls"]) + len(state["reserved"]) >= state["rate_limit"]:
                return False, f"rate cap exceeded (>= {state['rate_limit']} in window)"
            return True, "ok"

        return self.store.mutate_budget(agent_id, mutator)

    def reserve(self, agent_id: str, cost: float,
                now: Optional[float] = None) -> Tuple[Optional[str], str]:
        now = now if now is not None else time.time()

        def mutator(state: Dict) -> Tuple[Optional[str], str]:
            self._seed(agent_id, state)
            _prune(state, now)
            reserved = _reserved_sum(state)
            if state["spent"] + reserved + cost > state["spend_limit"]:
                return None, (f"spend cap exceeded ({state['spent']}+{reserved}+{cost} "
                              f"> {state['spend_limit']})")
            if len(state["calls"]) + len(state["reserved"]) >= state["rate_limit"]:
                return None, f"rate cap exceeded (>= {state['rate_limit']} in window)"
            token = uuid.uuid4().hex
            state["reserved"][token] = cost
            return token, "reserved"

        result = self.store.mutate_budget(agent_id, mutator)
        self._budgets.pop(agent_id, None)   # invalidate stale cache
        return result

    def commit(self, agent_id: str, token: str, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()

        def mutator(state: Dict) -> bool:
            self._seed(agent_id, state)
            if token not in state["reserved"]:
                return False
            cost = state["reserved"].pop(token)
            state["spent"] += cost
            state["calls"].append(now)
            return True

        result = self.store.mutate_budget(agent_id, mutator)
        self._budgets.pop(agent_id, None)
        return result

    def release(self, agent_id: str, token: str) -> bool:
        def mutator(state: Dict) -> bool:
            self._seed(agent_id, state)
            return state["reserved"].pop(token, None) is not None

        result = self.store.mutate_budget(agent_id, mutator)
        self._budgets.pop(agent_id, None)
        return result
