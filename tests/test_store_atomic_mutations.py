"""Legacy SQL mutations must not commit or abort the embedding transaction."""

import pytest

from src.governance.audit_trust import AuditTrustStore
from src.governance.store import sql_atomic


def seed(store):
    store.upsert_identity("agent", "original")
    store.append_audit({"seq": 1})
    store.append_audit({"seq": 2})
    store.insert_approval(dict(id="approval", agent_id="agent", capability="read", cost=1, status="pending"))


def mutate(store, operation):
    if operation == "identity":
        store.upsert_identity("agent", "replacement", revoked=True)
    elif operation == "audit-append":
        store.append_audit({"seq": 3})
    elif operation == "approval-insert":
        store.insert_approval(dict(id="new", agent_id="agent", capability="read", cost=1))
    elif operation == "approval-status":
        assert store.update_approval_status("approval", "approved")
    elif operation == "approval-delete":
        assert store.delete_approval("approval")
    elif operation == "audit-retain":
        assert store.truncate_audit_before(2) == 1
    else:
        raise AssertionError("unknown test operation")


def snapshot(store):
    return store.get_identity("agent"), store.load_audit(), store.list_approvals()


@pytest.mark.parametrize("operation", ["identity", "audit-append", "approval-insert", "approval-status", "approval-delete", "audit-retain"])
def test_legacy_mutation_preserves_outer_rollback(network_sql_stores, monkeypatch, operation):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store=network_sql_stores()
    seed(store)
    before=snapshot(store)
    with pytest.raises(RuntimeError, match="abort outer"):
        with sql_atomic(store):
            store.upsert_budget("marker", {"spent": 4})
            mutate(store,operation)
            raise RuntimeError("abort outer")
    assert snapshot(store)==before
    assert store.get_budget("marker") is None
    # The same method still persists a standalone successful operation.
    mutate(store,operation)
    assert snapshot(store)!=before


def test_missing_and_denied_updates_leave_outer_transaction_usable(network_sql_stores, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    store=network_sql_stores()
    seed(store)
    trust=AuditTrustStore(store)
    trust.set_hold("case",True)
    with sql_atomic(store):
        store.upsert_budget("marker", {"spent": 4})
        assert not store.update_approval_status("missing", "approved")
        assert not store.delete_approval("missing")
        with pytest.raises(PermissionError, match="durable legal hold"):
            store.truncate_audit_before(2)
        assert store.update_approval_status("approval", "approved")
        assert not store.update_approval_status("approval", "rejected")
    assert store.get_budget("marker")["spent"]==4
    assert store.get_approval("approval")["status"]=="approved"
    assert [entry['seq'] for entry in store.load_audit()]==[1,2]


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_production_raw_retention_stays_forbidden_inside_transaction(network_sql_stores, monkeypatch, environment):
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    store=network_sql_stores()
    seed(store)
    with sql_atomic(store):
        store.upsert_budget("marker", {"spent": 4})
        with pytest.raises(PermissionError, match="production audit retention"):
            store.truncate_audit_before(2)
    assert store.get_budget("marker")["spent"]==4
    assert [entry['seq'] for entry in store.load_audit()]==[1,2]
