"""
Governance plane tests — the moat.

Covers real Ed25519 identity verification, tamper-evident audit, budget enforcement,
policy decisions, and governance enforced in the actual cross-protocol call path.
"""

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("redis", MagicMock())
sys.modules.setdefault("redis.asyncio", MagicMock())

from src.governance import (
    AgentIdentity, IdentityRegistry, AuditLog, Budget, BudgetManager,
    PolicyEngine, GovernanceGateway, GovernanceError,
)
from src.protocols.canonical import CanonicalCall


# --- Identity (real Ed25519) ----------------------------------------------------------

def test_identity_sign_and_verify_roundtrip():
    ident = AgentIdentity.generate("agent-1")
    sig = ident.sign(b"hello")
    assert ident.verify(b"hello", sig) is True
    assert ident.verify(b"tampered", sig) is False
    assert ident.did.startswith("did:key:ed25519:")


def test_registry_verifies_only_registered_agents():
    reg = IdentityRegistry()
    ident = AgentIdentity.generate("agent-1")
    reg.register(ident)
    sig = ident.sign(b"payload")
    assert reg.verify_signature("agent-1", b"payload", sig) is True
    assert reg.verify_signature("agent-1", b"evil", sig) is False
    assert reg.verify_signature("unknown", b"payload", sig) is False
    # The registered copy must not carry the private key.
    assert reg.get("agent-1")._private_key is None


# --- Audit (hash-chained tamper evidence) ---------------------------------------------

def test_audit_chain_integrity_and_tamper_detection():
    log = AuditLog()
    for i in range(3):
        log.record(actor="a", action="route_call", source_protocol="openai",
                   target_protocol="mcp", capability="add", decision="allow", cost=1.0)
    assert log.verify_integrity() is True
    # Tamper with a past entry -> chain breaks.
    log.entries()[1].capability = "rm -rf"
    assert log.verify_integrity() is False


# --- Budget ---------------------------------------------------------------------------

def test_budget_spend_and_rate_caps():
    b = Budget(spend_limit=2.0, rate_limit=3, window_seconds=3600)
    ok, _ = b.can_afford(1.0); assert ok
    b.charge(1.0); b.charge(1.0)
    ok, why = b.can_afford(1.0); assert not ok and "spend" in why
    # Rate cap independent of spend.
    b2 = Budget(spend_limit=100.0, rate_limit=2)
    b2.charge(0); b2.charge(0)
    ok, why = b2.can_afford(0); assert not ok and "rate" in why


# --- Policy ---------------------------------------------------------------------------

def test_policy_denies_unknown_capability_and_budget():
    ids = IdentityRegistry(); buds = BudgetManager()
    ident = AgentIdentity.generate("a"); ids.register(ident)
    pol = PolicyEngine(ids, buds)
    assert pol.authorize(agent_id="ghost", capability="add").allowed is False  # unknown id
    pol.allow_capability("a", "add")
    assert pol.authorize(agent_id="a", capability="delete").allowed is False    # not allowed
    assert pol.authorize(agent_id="a", capability="add").allowed is True


# --- Gateway: governance enforced in the cross-protocol call path ----------------------

def _make_gateway():
    ids = IdentityRegistry(); buds = BudgetManager()
    buds.set_budget("caller", Budget(spend_limit=2.0, rate_limit=100))
    gw = GovernanceGateway(identities=ids, budgets=buds)
    return gw, ids


async def _invoke_echo(dst_wire):
    # Pretend target returns the tool name it was asked for.
    return {"ok": True, "called": dst_wire.get("params", {}).get("name")}


def test_gateway_denies_unverified_then_allows_verified_and_audits():
    gw, ids = _make_gateway()
    openai_call = gw.registry.get("openai").from_canonical_call(
        CanonicalCall("add", {"a": 1}))

    # Unverified caller is denied and the denial is audited.
    with pytest.raises(GovernanceError):
        asyncio.run(gw.route_call(agent_id="caller", src_proto="openai", dst_proto="mcp",
                                  src_wire=openai_call, invoke=_invoke_echo))
    assert gw.audit.entries()[-1].decision == "deny"

    # Register the caller -> now allowed, routed openai->mcp, budget charged, audited.
    ids.register(AgentIdentity.generate("caller"))
    res = asyncio.run(gw.route_call(agent_id="caller", src_proto="openai", dst_proto="mcp",
                                    src_wire=openai_call, invoke=_invoke_echo, cost=1.0))
    assert res["called"] == "add"
    assert gw.audit.entries()[-1].decision == "allow"
    assert gw.budgets.get("caller").spent == 1.0
    assert gw.audit.verify_integrity() is True


def test_gateway_enforces_budget_exhaustion():
    gw, ids = _make_gateway()
    ids.register(AgentIdentity.generate("caller"))
    call = gw.registry.get("mcp").from_canonical_call(
        CanonicalCall("add", {"a": 1}))

    # spend_limit=2.0; two calls at cost 1.0 ok, third denied.
    for _ in range(2):
        asyncio.run(gw.route_call(agent_id="caller", src_proto="mcp", dst_proto="a2a",
                                  src_wire=call, invoke=_invoke_echo, cost=1.0))
    with pytest.raises(GovernanceError):
        asyncio.run(gw.route_call(agent_id="caller", src_proto="mcp", dst_proto="a2a",
                                  src_wire=call, invoke=_invoke_echo, cost=1.0))
    assert gw.audit.verify_integrity() is True
