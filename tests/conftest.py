"""
Shared pytest fixtures for AgentBridge tests.

Uses the REAL governance API (see src/governance). Fixtures are opt-in — a test only
pays for one it requests by name — so this file adds reusable setup without changing
how the existing self-contained tests run.
"""

import os
import sys

import pytest

# Make `src` importable however pytest is invoked — bare `pytest` (as CI runs it) does not put
# the repo root on sys.path the way `python -m pytest` does.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.governance import (
    make_store,
    AgentIdentity,
    IdentityRegistry,
    BudgetManager,
    PolicySet,
    MaxCostPerCall,
    RequireApprovalAboveCost,
    DenyCapabilities,
    BusinessHoursOnly,
)


@pytest.fixture
def in_memory_store():
    """A fresh in-memory governance store."""
    return make_store(None)


@pytest.fixture
def sqlite_store(tmp_path):
    """A durable SQLite store in a per-test temp dir (closed on teardown)."""
    store = make_store(str(tmp_path / "governance.db"))
    yield store
    if hasattr(store, "close"):
        store.close()


@pytest.fixture
def sample_identity():
    """A freshly generated Ed25519 agent identity."""
    return AgentIdentity.generate("agent-test-001")


@pytest.fixture
def identities(sample_identity):
    """An IdentityRegistry with one registered agent."""
    reg = IdentityRegistry()
    reg.register(sample_identity)
    return reg


@pytest.fixture
def budgets(in_memory_store):
    """A store-backed BudgetManager."""
    return BudgetManager(store=in_memory_store)


@pytest.fixture
def sample_policy():
    """A representative PolicySet using the real rule signatures."""
    return PolicySet([
        MaxCostPerCall(10),
        RequireApprovalAboveCost(5),
        DenyCapabilities(["wire_transfer"]),
        BusinessHoursOnly(9, 17, days=[0, 1, 2, 3, 4]),
    ])
