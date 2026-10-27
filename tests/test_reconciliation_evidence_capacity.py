"""Evidence saturation must preserve UNKNOWN, holds and every SQL participant.

Synthetic local signatures exercise verification, not independent custody.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustStore
from src.governance.budget import Budget, BudgetManager
from src.governance.destination_receipts import canonical_receipt_payload
from src.governance.identity import AgentIdentity
from src.governance.operation_ledger import OperationLedger
from src.governance.operator_review import canonical_review_payload
from src.governance.readback_attestations import canonical_readback_payload
from src.governance.reconciliation import Reconciliation, ReconciliationError
from src.governance.store import PostgresStore, SqliteStore, sql_atomic
from tests.test_authority import authority as authority
from tests.test_tenant_store import namespaces as namespaces


def execute(store, sql, args=()):
    return store._db.execute(sql.replace("?", "%s") if isinstance(store, PostgresStore) else sql, args)


def database_error(store):
    if isinstance(store, SqliteStore):
        return sqlite3.DatabaseError
    import psycopg
    return psycopg.Error


def unknown(store, operation="fixture-operation-123456"):
    manager = BudgetManager(store)
    manager.set_budget("fixture-agent", Budget(spend_limit=20))
    token, reason = manager.reserve("fixture-agent", 3)
    assert token, reason
    OperationLedger(store).claim("fixture-agent", operation, "fixture-fingerprint", reservation_token=token)
    return dict(agent_id="fixture-agent", operation_id=operation, result="succeeded",
                external_reference="synthetic:no-remote-effect", reviewer="fixture-operator",
                evidence_sha256=hashlib.sha256(b"synthetic-only").hexdigest())


def protected(store):
    tables = ("agent_operations", "operation_reservations", "operation_reconciliations",
              "reconciliation_readbacks", "reconciliation_evidence", "evidence_capacity_policy_v1",
              "audit_capacity_policy_v1", "audit_holds")
    return {"budget": store.get_budget("fixture-agent"), "audit": store.load_audit(),
            "tables": {name: [dict(row) for row in execute(store, "SELECT * FROM " + name + " ORDER BY 1,2")]
                       for name in tables}}


@pytest.mark.parametrize("boundary", ["count", "bytes", "entry"])
@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_evidence_only_saturation_preserves_all_settlement_participants(network_sql_stores, boundary, outcome):
    store = network_sql_stores()
    rec = Reconciliation(store)
    AuditTrustStore(store).set_hold("preserved-case", True)
    kwargs = {**unknown(store), "result": outcome}
    limits = dict(max_records=10, max_bytes=4096, max_entry_bytes=4096)
    if boundary == "count":
        limits["max_records"] = 1
    elif boundary == "bytes":
        limits.update(max_bytes=150, max_entry_bytes=150)
    else:
        limits["max_entry_bytes"] = 100
    rec.set_evidence_capacity(**limits)
    execute(store, "INSERT INTO reconciliation_evidence VALUES(?,?,?)", ("old", "preserved", "x" * 100))
    assert AuditTrustStore(store).capacity()["used_records"] == 0
    before = protected(store)
    with pytest.raises(database_error(store), match="evidence capacity"):
        rec.record(**kwargs)
    assert protected(store) == before
    assert OperationLedger(store).get("fixture-agent", kwargs["operation_id"])["state"] == "unknown"
    assert store.get_budget("fixture-agent")["spent"] == 0
    assert list(store.get_budget("fixture-agent")["reserved"].values()) == [3]
    # Recovery is explicit operator configuration and settlement, never replay.
    rec.set_evidence_capacity(max_records=10, max_bytes=4096, max_entry_bytes=4096)
    assert rec.record(**kwargs)["state"] == outcome
    assert store.get_budget("fixture-agent")["reserved"] == {}
    assert store.get_budget("fixture-agent")["spent"] == (3 if outcome == "succeeded" else 0)
    assert AuditTrustStore(store).holds() == ["preserved-case"]
    assert AuditLog.verify_chain(store.load_audit(), require_genesis=True)


def signed(store, monkeypatch, outcome="succeeded"):
    kwargs = {**unknown(store), "result": outcome}
    signers = [AgentIdentity.generate(name) for name in ("destination", "observer", "operator")]
    receipt = {name: kwargs[name] for name in ("agent_id", "operation_id", "external_reference")}
    receipt.update(fingerprint="fixture-fingerprint", outcome=outcome)
    receipt["signature_hex"] = signers[0].sign(canonical_receipt_payload(receipt)).hex()
    kwargs["evidence_sha256"] = hashlib.sha256(canonical_receipt_payload(receipt)).hexdigest()
    proof = {**{name: receipt[name] for name in ("agent_id", "operation_id", "fingerprint", "external_reference", "outcome")},
             "observed_at": int(time.time()), "source": "synthetic-separately-keyed-observer",
             "source_evidence_sha256": hashlib.sha256(b"synthetic-readback").hexdigest(),
             "destination_receipt_sha256": kwargs["evidence_sha256"]}
    proof["signature_hex"] = signers[1].sign(canonical_readback_payload(proof)).hex()
    review = dict(reviewer=kwargs["reviewer"], **{name: receipt[name] for name in
                  ("agent_id", "operation_id", "fingerprint", "outcome", "external_reference")},
                  destination_receipt_sha256=kwargs["evidence_sha256"],
                  readback_sha256=hashlib.sha256(canonical_readback_payload(proof)).hexdigest())
    kwargs.update(destination_receipt=receipt, readback_attestation=proof,
                  reviewer_signature_hex=signers[2].sign(canonical_review_payload(review)).hex())
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", signers[0].public_key_hex)
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", signers[1].public_key_hex)
    monkeypatch.setenv("AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON", json.dumps({kwargs["reviewer"]: signers[2].public_key_hex}))
    return kwargs


@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_verified_bundle_capacity_and_original_digest_binding(network_sql_stores, monkeypatch, outcome):
    store = network_sql_stores()
    rec = Reconciliation(store)
    AuditTrustStore(store).set_hold("signed-case", True)
    kwargs = signed(store, monkeypatch, outcome)
    rec.set_evidence_capacity(max_records=1, max_bytes=65536, max_entry_bytes=1)
    before = protected(store)
    with pytest.raises(ReconciliationError, match="untrusted destination"):
        rec.record(**{**kwargs, "destination_receipt": {**kwargs["destination_receipt"], "fingerprint": "wrong"}})
    assert protected(store) == before
    with pytest.raises(database_error(store), match="evidence capacity"):
        rec.record(**kwargs)
    assert protected(store) == before
    rec.set_evidence_capacity(max_records=1, max_bytes=65536, max_entry_bytes=65536)
    assert rec.record(**kwargs)["state"] == outcome
    expected = json.dumps({name: kwargs[name] for name in
                         ("destination_receipt", "readback_attestation", "reviewer_signature_hex")} |
                         {"trust_context": {}}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    actual = execute(store, "SELECT bundle FROM reconciliation_evidence").fetchone()["bundle"]
    assert actual.encode("utf-8") == expected.encode("utf-8")
    reason = json.loads(store.load_audit()[-1]["reason"])
    assert reason["evidence_bundle_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert rec.evidence_capacity()["used_bytes"] == len(expected.encode("utf-8"))
    assert len(list(execute(store, "SELECT * FROM reconciliation_readbacks"))) == 1
    assert AuditTrustStore(store).holds() == ["signed-case"]


def test_post_append_exception_and_outer_rollback_preserve_unknown(network_sql_stores, monkeypatch):
    store = network_sql_stores()
    rec = Reconciliation(store)
    AuditTrustStore(store).set_hold("rollback-case", True)
    kwargs = unknown(store)
    rec.evidence_capacity()
    before = protected(store)
    original = rec._append_settlement_evidence
    def fail(*args, **values):
        original(*args, **values)
        raise RuntimeError("after append before commit")
    with monkeypatch.context() as patch:
        patch.setattr(rec, "_append_settlement_evidence", fail)
        with pytest.raises(RuntimeError, match="before commit"):
            rec.record(**kwargs)
    assert protected(store) == before
    with pytest.raises(RuntimeError, match="outer rollback"):
        with sql_atomic(store):
            rec.record(**kwargs)
            raise RuntimeError("outer rollback")
    assert protected(store) == before


def test_audit_saturation_rolls_back_signed_bundle_readback_and_settlement(network_sql_stores, monkeypatch):
    store = network_sql_stores()
    rec = Reconciliation(store)
    trust = AuditTrustStore(store)
    trust.set_hold("audit-saturation-case", True)
    AuditLog(store).record(actor="fixture", action="existing", source_protocol="test",
                           target_protocol="test", capability="read", decision="allow")
    trust.set_capacity(max_records=1, max_bytes=65536, max_entry_bytes=65536)
    kwargs = signed(store, monkeypatch)
    assert rec.evidence_capacity()["used_records"] == 0
    before = protected(store)
    with pytest.raises(database_error(store), match="audit capacity"):
        rec.record(**kwargs)
    assert protected(store) == before
    assert OperationLedger(store).get("fixture-agent", kwargs["operation_id"])["state"] == "unknown"


def test_nonproduction_oversized_optional_bundle_fails_without_settlement(network_sql_stores, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "test")
    store = network_sql_stores()
    rec = Reconciliation(store)
    AuditTrustStore(store).set_hold("large-case", True)
    kwargs = unknown(store)
    rec.evidence_capacity()
    before = protected(store)
    with pytest.raises(database_error(store), match="evidence capacity"):
        rec.record(**kwargs, destination_receipt={"legacy_optional_extension": "x" * (300 * 1024)})
    assert protected(store) == before


def test_concurrent_real_settlements_share_last_evidence_slot(network_sql_stores):
    setup = network_sql_stores()
    rec = Reconciliation(setup)
    AuditTrustStore(setup).set_hold("concurrent-case", True)
    rec.set_evidence_capacity(max_records=1, max_bytes=65536, max_entry_bytes=65536)
    workers = [network_sql_stores(), network_sql_stores()]
    calls = []
    # Distinct agent budgets avoid a same-budget mutex masking the quota race.
    for index, own in enumerate(workers):
        agent, operation = "worker-" + str(index), "operation-concurrent-" + str(index)
        budgets = BudgetManager(own)
        budgets.set_budget(agent, Budget(spend_limit=10))
        token, _ = budgets.reserve(agent, 3)
        OperationLedger(own).claim(agent, operation, "scope", reservation_token=token)
        calls.append(dict(agent_id=agent, operation_id=operation, result="succeeded", reviewer="fixture",
                          external_reference="synthetic", evidence_sha256="a" * 64))
    authorities = [Reconciliation(own) for own in workers]
    barrier = threading.Barrier(2)
    def run(index):
        barrier.wait(timeout=15)
        try:
            authorities[index].record(**calls[index])
            return True
        except database_error(workers[index]) as exc:
            assert "evidence capacity" in str(exc)
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(results) == 1
    assert rec.evidence_capacity()["used_records"] == len(setup.load_audit()) == 1
    for index, accepted in enumerate(results):
        state = OperationLedger(setup).get(calls[index]["agent_id"], calls[index]["operation_id"])
        budget = setup.get_budget(calls[index]["agent_id"])
        assert state["state"] == ("succeeded" if accepted else "unknown")
        assert budget["spent"] == (3 if accepted else 0)
        assert sum(budget["reserved"].values()) == (0 if accepted else 3)
    assert AuditTrustStore(setup).holds() == ["concurrent-case"]


def test_late_created_evidence_policy_retains_tenant_write_boundary(authority, namespaces):
    scoped, beta = namespaces("alpha"), namespaces("beta")
    a, b = Reconciliation(scoped), Reconciliation(beta)
    assert a.evidence_capacity()["used_records"] == b.evidence_capacity()["used_records"] == 0
    a.set_evidence_capacity(max_records=1, max_bytes=1000, max_entry_bytes=1000)
    assert b.evidence_capacity()["max_records"] == 100000
    legacy = namespaces("alpha", legacy=True)
    with pytest.raises(Exception, match="agentbridge_current_tenant|tenant write scope required"):
        execute(legacy, "UPDATE evidence_capacity_policy_v1 SET max_records=2 WHERE singleton=1")
    with pytest.raises(Exception, match="agentbridge_current_tenant|tenant write scope required"):
        execute(legacy, "INSERT INTO reconciliation_evidence VALUES('old','writer','payload')")
    assert a.evidence_capacity()["max_records"] == 1
    assert a.evidence_capacity()["used_records"] == b.evidence_capacity()["used_records"] == 0


@pytest.mark.parametrize("boundary", ["before-commit", "lost-ack"])
def test_sqlite_process_crash_and_restart_never_replay(tmp_path, boundary):
    path = tmp_path / "crash.sqlite"
    store = SqliteStore(str(path))
    rec = Reconciliation(store)
    AuditTrustStore(store).set_hold("crash-case", True)
    kwargs = unknown(store)
    rec.evidence_capacity()
    before = protected(store)
    store.close()
    script = '''
import json,os,sys
from src.governance.store import SqliteStore
from src.governance.reconciliation import Reconciliation
store=SqliteStore(sys.argv[1]); rec=Reconciliation(store)
if sys.argv[2]=='before-commit':
    original=rec._append_settlement_evidence
    def crash(*args,**kwargs):
        original(*args,**kwargs)
        os._exit(37)
    rec._append_settlement_evidence=crash
rec.record(**json.loads(sys.argv[3]))
os._exit(38)
'''
    environment = {key: value for key, value in os.environ.items() if key != "AGENTBRIDGE_TEST_PG"}
    process = subprocess.run([sys.executable, "-c", script, str(path), boundary, json.dumps(kwargs)],
                             env=environment, capture_output=True, timeout=30)
    assert process.returncode == (37 if boundary == "before-commit" else 38), process.stderr.decode(errors="replace")
    restarted = SqliteStore(str(path))
    try:
        current = Reconciliation(restarted)
        if boundary == "before-commit":
            assert protected(restarted) == before
            assert current.evidence_capacity()["used_records"] == 0
        else:
            assert OperationLedger(restarted).get("fixture-agent", kwargs["operation_id"])["state"] == "succeeded"
            assert current.evidence_capacity()["used_records"] == 1
            assert restarted.get_budget("fixture-agent")["spent"] == 3
            settled = protected(restarted)
            with pytest.raises(ReconciliationError, match="no longer unknown"):
                current.record(**kwargs)
            assert protected(restarted) == settled
        assert AuditTrustStore(restarted).holds() == ["crash-case"]
    finally:
        restarted.close()
