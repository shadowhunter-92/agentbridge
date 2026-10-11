"""Cross-worker governance configuration regression tests."""
from pathlib import Path
from src.governance.store import SqliteStore
from src.governance.durable_policy import DurablePolicySet, DurableApprovalQueue
from src.governance.policy_rules import DenyCapabilities, PolicyContext


def test_policy_rules_are_shared_and_survive_restart(tmp_path: Path):
    path = str(tmp_path / "policy.db")
    a, b = SqliteStore(path), SqliteStore(path)
    try:
        first, second = DurablePolicySet(a), DurablePolicySet(b)
        assert second.evaluate(PolicyContext("x", "delete")).allowed
        first.add(DenyCapabilities(["delete"]))
        assert not second.evaluate(PolicyContext("x", "delete")).allowed
        assert len(second.rules) == 1
    finally:
        a.close()
        b.close()


def test_sensitive_policy_is_shared_across_workers(tmp_path: Path):
    path = str(tmp_path / "sensitive.db")
    a, b = SqliteStore(path), SqliteStore(path)
    try:
        first, second = DurableApprovalQueue(a), DurableApprovalQueue(b)
        assert not second.requires_approval("transfer")
        first.mark_sensitive("transfer")
        assert second.requires_approval("transfer")
    finally:
        a.close()
        b.close()
