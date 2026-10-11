"""Durable governance configuration shared across SQL-backed workers.

Dynamic policy rules and sensitive-capability flags must not depend on which
worker receives a request. SQL reads are authoritative; no stale config cache.
"""
from __future__ import annotations

import json
from .store import InMemoryStore, SqliteStore, PostgresStore
from .approvals import ApprovalQueue
from .policy_rules import (
    PolicySet, MaxCostPerCall, RequireApprovalAboveCost,
    DenyCapabilities, AllowOnlyCapabilities, BusinessHoursOnly, DenyProtocolRoute,
)


def _rule_to_dict(rule):
    if isinstance(rule, MaxCostPerCall):
        return {"kind": "max_cost", "max_cost": rule.max_cost}
    if isinstance(rule, RequireApprovalAboveCost):
        return {"kind": "approval_above_cost", "threshold": rule.threshold}
    if isinstance(rule, DenyCapabilities):
        return {"kind": "deny_capabilities", "capabilities": sorted(rule.caps)}
    if isinstance(rule, AllowOnlyCapabilities):
        return {"kind": "allow_only_capabilities", "capabilities": sorted(rule.caps)}
    if isinstance(rule, BusinessHoursOnly):
        return {"kind": "business_hours", "start_hour": rule.start, "end_hour": rule.end,
                "days": sorted(rule.days)}
    if isinstance(rule, DenyProtocolRoute):
        return {"kind": "deny_route", "src": rule.src, "dst": rule.dst}
    raise ValueError("Only built-in, serializable policy rules are allowed in durable configuration")


def _rule_from_dict(data):
    kind = data["kind"]
    if kind == "max_cost":
        return MaxCostPerCall(data["max_cost"])
    if kind == "approval_above_cost":
        return RequireApprovalAboveCost(data["threshold"])
    if kind == "deny_capabilities":
        return DenyCapabilities(data["capabilities"])
    if kind == "allow_only_capabilities":
        return AllowOnlyCapabilities(data["capabilities"])
    if kind == "business_hours":
        return BusinessHoursOnly(data["start_hour"], data["end_hour"], data["days"])
    if kind == "deny_route":
        return DenyProtocolRoute(data["src"], data["dst"])
    raise ValueError("Unknown policy rule kind in durable configuration")


class DurablePolicySet(PolicySet):
    def __init__(self, store):
        self.store = store
        super().__init__()
        if isinstance(store, SqliteStore):
            with store._lock:
                store._db.execute(
                    "CREATE TABLE IF NOT EXISTS governance_rules ("
                    "seq INTEGER PRIMARY KEY AUTOINCREMENT, definition TEXT NOT NULL)")
        elif isinstance(store, PostgresStore):
            with store._lock, store._db.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS governance_rules ("
                    "seq BIGSERIAL PRIMARY KEY, definition TEXT NOT NULL)")

    @property
    def rules(self):
        if isinstance(self.store, InMemoryStore):
            return self._local_rules
        with self.store._lock:
            if isinstance(self.store, SqliteStore):
                rows = self.store._db.execute(
                    "SELECT definition FROM governance_rules ORDER BY seq").fetchall()
                values = [row["definition"] for row in rows]
            else:
                with self.store._db.cursor() as cur:
                    cur.execute("SELECT definition FROM governance_rules ORDER BY seq")
                    values = [row["definition"] for row in cur.fetchall()]
        return [_rule_from_dict(json.loads(value)) for value in values]

    @rules.setter
    def rules(self, value):
        self._local_rules = value

    def add(self, rule):
        if isinstance(self.store, InMemoryStore):
            return super().add(rule)
        data = json.dumps(_rule_to_dict(rule), sort_keys=True)
        with self.store._lock:
            if isinstance(self.store, SqliteStore):
                self.store._db.execute(
                    "INSERT INTO governance_rules(definition) VALUES(?)", (data,))
            else:
                with self.store._db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO governance_rules(definition) VALUES(%s)", (data,))
        return self


class DurableApprovalQueue(ApprovalQueue):
    def __init__(self, store):
        super().__init__(store=store)
        if isinstance(store, SqliteStore):
            with store._lock:
                store._db.execute(
                    "CREATE TABLE IF NOT EXISTS sensitive_capabilities ("
                    "capability TEXT PRIMARY KEY)")
        elif isinstance(store, PostgresStore):
            with store._lock, store._db.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS sensitive_capabilities ("
                    "capability TEXT PRIMARY KEY)")

    def mark_sensitive(self, capability):
        if isinstance(self.store, InMemoryStore):
            return super().mark_sensitive(capability)
        if not isinstance(capability, str) or not capability:
            raise ValueError("capability must be nonempty")
        with self.store._lock:
            if isinstance(self.store, SqliteStore):
                self.store._db.execute(
                    "INSERT OR IGNORE INTO sensitive_capabilities(capability) VALUES(?)",
                    (capability,))
            else:
                with self.store._db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sensitive_capabilities(capability) VALUES(%s) "
                        "ON CONFLICT(capability) DO NOTHING", (capability,))

    def requires_approval(self, capability):
        if isinstance(self.store, InMemoryStore):
            return super().requires_approval(capability)
        with self.store._lock:
            if isinstance(self.store, SqliteStore):
                row = self.store._db.execute(
                    "SELECT 1 FROM sensitive_capabilities WHERE capability=?",
                    (capability,)).fetchone()
            else:
                with self.store._db.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM sensitive_capabilities WHERE capability=%s",
                        (capability,))
                    row = cur.fetchone()
            return row is not None
