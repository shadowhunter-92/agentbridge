"""
Governance plane v2 tests: durability, real request auth, atomic budgets, approvals.
These cover the deep-review fixes (H1 auth, H2 persistence, H3 race, P2 approvals/revocation).
"""

import os
import tempfile
import threading

import pytest

from src.governance import (
    AgentIdentity, IdentityRegistry, BudgetManager, Budget, AuditLog,
    SqliteStore, RequestAuthenticator, sign_request, canonical_payload,
    ApprovalQueue, PolicyEngine,
)


# --- H2: durability across "restart" (new objects, same SQLite file) ------------------

def test_sqlite_persistence_survives_restart():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gov.db")

        store1 = SqliteStore(path)
        ids1 = IdentityRegistry(store=store1)
        ident = AgentIdentity.generate("agent-A")
        ids1.register(ident)
        buds1 = BudgetManager(store=store1)
        buds1.set_budget("agent-A", Budget(spend_limit=10))
        buds1.get("agent-A").charge(3.0)
        buds1.persist("agent-A")
        log1 = AuditLog(store=store1)
        log1.record(actor="agent-A", action="route_call", source_protocol="mcp",
                    target_protocol="a2a", capability="add", decision="allow", cost=1.0)

        # "Restart": brand-new objects from a fresh store on the same file.
        store2 = SqliteStore(path)
        ids2 = IdentityRegistry(store=store2)
        assert ids2.is_registered("agent-A")
        assert ids2.did_of("agent-A") == ident.did
        buds2 = BudgetManager(store=store2)
        assert buds2.get("agent-A").spent == 3.0
        log2 = AuditLog(store=store2)
        assert len(log2.entries()) == 1
        assert log2.verify_integrity() is True

        store1.close()
        store2.close()


# --- H1: real signed-request authentication ------------------------------------------

def test_request_authentication_and_replay_and_revocation():
    ids = IdentityRegistry()
    agent = AgentIdentity.generate("signer")
    ids.register(agent)
    auth = RequestAuthenticator(ids)

    body = b'{"hello":"world"}'
    nonce = "nonce-1"
    sig = sign_request(agent, nonce, body)

    ok, _ = auth.authenticate("signer", nonce, body, sig)
    assert ok
    # Replay same nonce -> rejected.
    ok2, why2 = auth.authenticate("signer", nonce, body, sig)
    assert not ok2 and "replay" in why2
    # Tampered body -> signature fails.
    ok3, _ = auth.authenticate("signer", "nonce-2", b'{"hello":"evil"}', sig)
    assert not ok3
    # Revoked identity -> rejected.
    ids.revoke("signer")
    ok4, why4 = auth.authenticate("signer", "nonce-3", body, sign_request(agent, "nonce-3", body))
    assert not ok4


# --- H3: atomic budget under concurrency ---------------------------------------------

def test_atomic_budget_no_overrun_under_concurrency():
    # spend_limit 10, cost 1 each, 50 threads -> at most 10 commits, never more.
    b = Budget(spend_limit=10.0, rate_limit=10_000)
    committed = []

    def worker():
        token, _ = b.reserve(1.0)
        if token is not None:
            b.commit(token)
            committed.append(1)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert sum(committed) == 10
    assert b.spent == 10.0
    assert b.remaining() == 0.0


def test_reserve_release_returns_capacity():
    b = Budget(spend_limit=2.0)
    t1, _ = b.reserve(1.0)
    t2, _ = b.reserve(1.0)
    assert b.reserve(1.0)[0] is None        # full (2 reserved)
    b.release(t1)
    assert b.reserve(1.0)[0] is not None     # capacity freed


# --- P2: approvals + capability allowlist via policy ----------------------------------

def test_sensitive_capability_requires_approval():
    ids = IdentityRegistry(); buds = BudgetManager(); appr = ApprovalQueue()
    ids.register(AgentIdentity.generate("a"))
    appr.mark_sensitive("wire_transfer")
    pol = PolicyEngine(ids, buds, approvals=appr)

    d = pol.authorize(agent_id="a", capability="wire_transfer")
    assert not d.allowed and d.needs_approval
    # Operator approves -> now allowed (one-shot).
    req = appr.request("a", "wire_transfer", 1.0)
    appr.approve(req.id)
    assert pol.authorize(agent_id="a", capability="wire_transfer").allowed is True
