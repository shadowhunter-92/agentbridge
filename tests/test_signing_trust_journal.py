"""Signed trust-policy changes, restart/rollback and atomic settlement boundaries."""

import copy
import hashlib
import json
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from examples.qualify_trust_evidence import public, run_qualification, signed_registry
from src.governance.audit import AuditLog
from src.governance.budget import Budget, BudgetManager
from src.governance.destination_receipts import canonical_receipt_payload
from src.governance.observer_key_registry import (
    ObserverKey,
    ObserverKeyDenied,
    ObserverTrustRegistry,
)
from src.governance.operation_ledger import OperationLedger
from src.governance.operator_review import canonical_review_payload
from src.governance.readback_attestations import canonical_readback_payload
from src.governance.reconciliation import Reconciliation, ReconciliationError
from src.governance.sandbox_readback import SandboxReadOnlyObserver, SandboxTarget
from src.governance.signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from src.governance.store import PostgresStore, SqliteStore


@pytest.fixture(params=["sqlite", "postgres"])
def durable_store(request, tmp_path):
    if request.param == "sqlite":
        store = SqliteStore(str(tmp_path / "governance.sqlite"))
        try:
            yield store
        finally:
            store.close()
    else:
        dsn = os.getenv("AGENTBRIDGE_TEST_PG")
        if not dsn:
            pytest.skip("explicit disposable PostgreSQL required")
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        schema = "ab_trust_test_" + uuid.uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            store = PostgresStore(make_conninfo(dsn, options="-csearch_path=" + schema))
            try:
                yield store
            finally:
                store.close()
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def configured(durable_store):
    controllers = {domain: Ed25519PrivateKey.generate() for domain in ("destination", "readback")}
    signer = {domain: Ed25519PrivateKey.generate() for domain in controllers}
    pinned = {domain: public(key) for domain, key in controllers.items()}
    trust = SigningTrustJournal(durable_store, controller_keys=pinned)
    envelopes = {}
    for domain in controllers:
        envelopes[domain] = signed_registry(
            controllers[domain],
            domain,
            1,
            None,
            [dict(key_id="old", public_key_hex=public(signer[domain]), state="active")],
        )
        trust.publish(envelopes[domain])
    return durable_store, trust, controllers, signer, envelopes, pinned


def resolve(trust):
    with trust._transaction() as cur:
        return trust.settlement_keys(cur, destination_key_id="old", observer_key_id="old")


def test_restart_reloads_signed_policy_and_idempotent_publication(configured):
    store, trust, _, signer, envelopes, pinned = configured
    assert trust.publish(envelopes["destination"])
    reloaded = SigningTrustJournal(store, controller_keys=pinned)
    assert resolve(reloaded)["destination_key_hex"] == public(signer["destination"])


@pytest.mark.parametrize("mutation", ["signature", "domain", "revision", "predecessor", "metadata", "key"])
def test_untrusted_registry_updates_fail_closed(configured, mutation):
    _, trust, controllers, _, envelopes, _ = configured
    candidate = signed_registry(
        controllers["readback"],
        "readback",
        2,
        envelopes["readback"],
        copy.deepcopy(envelopes["readback"]["keys"]),
    )
    if mutation == "signature":
        candidate["signature_hex"] = "00" * 64
    elif mutation == "domain":
        candidate["domain"] = "destination"
    elif mutation == "revision":
        candidate["revision"] = True
    elif mutation == "predecessor":
        candidate["previous_sha256"] = "1" * 64
    elif mutation == "metadata":
        candidate["unsigned_claim"] = "injected"
    else:
        candidate["keys"][0]["public_key_hex"] = public(Ed25519PrivateKey.generate())
    with pytest.raises(TrustJournalDenied):
        trust.publish(candidate)
    assert resolve(trust)["readback_revision"] == 1


def test_signed_rotation_cannot_skip_staging_or_resurrect(configured):
    _, trust, controllers, signer, envelopes, _ = configured
    added = dict(
        key_id="replacement",
        public_key_hex=public(Ed25519PrivateKey.generate()),
        state="active",
    )
    old = dict(envelopes["readback"]["keys"][0])
    with pytest.raises(TrustJournalDenied):
        trust.publish(
            signed_registry(
                controllers["readback"],
                "readback",
                2,
                envelopes["readback"],
                [old, added],
            )
        )
    added["state"] = "staged"
    staged = signed_registry(controllers["readback"], "readback", 2, envelopes["readback"], [old, added])
    trust.publish(staged)
    old["state"], added["state"] = "revoked", "active"
    rotated = signed_registry(controllers["readback"], "readback", 3, staged, [old, added])
    trust.publish(rotated)
    with pytest.raises(TrustJournalDenied):
        resolve(trust)
    old["state"] = "active"
    with pytest.raises(TrustJournalDenied):
        trust.publish(signed_registry(controllers["readback"], "readback", 4, rotated, [old, added]))


def test_restore_below_external_revision_pin_is_denied(configured):
    store, trust, _, _, _, pinned = configured
    externally_pinned = SigningTrustJournal(
        store,
        controller_keys=pinned,
        minimum_revisions={"destination": 2, "readback": 2},
    )
    with pytest.raises(TrustJournalDenied, match="minimum"):
        resolve(externally_pinned)
    assert resolve(trust)["destination_revision"] == 1


def test_corrupt_history_is_reverified(configured):
    store, trust, _, _, envelopes, _ = configured
    corrupted = copy.deepcopy(envelopes["readback"])
    corrupted["keys"][0]["state"] = "revoked"
    p = "?" if isinstance(store, SqliteStore) else "%s"
    store._db.execute(
        f"UPDATE signing_trust_revisions SET envelope={p} WHERE domain='readback'",
        (json.dumps(corrupted),),
    )
    with pytest.raises(TrustJournalDenied):
        resolve(trust)


def settlement_fixture(configured, tmp_path, monkeypatch):
    store, trust, _, signer, _, _ = configured
    reviewer = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    monkeypatch.setenv(
        "AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON",
        json.dumps({"reviewer": public(reviewer)}),
    )
    budgets = BudgetManager(store)
    budgets.set_budget("agent", Budget(spend_limit=10))
    token, _ = budgets.reserve("agent", 2)
    OperationLedger(store).claim("agent", "operation-00001", "fingerprint", reservation_token=token)
    path = str(tmp_path / "target.sqlite")
    with SandboxTarget(path, sign=signer["destination"].sign) as target:
        target.commit(agent_id="agent", operation_id="operation-00001", fingerprint="fingerprint")
    with SandboxReadOnlyObserver(
        path,
        destination_public_key_hex=public(signer["destination"]),
        sign=signer["readback"].sign,
    ) as observer:
        receipt, proof = observer.observe(agent_id="agent", operation_id="operation-00001", fingerprint="fingerprint")
    digest = hashlib.sha256(canonical_receipt_payload(receipt)).hexdigest()
    statement = dict(
        reviewer="reviewer",
        agent_id="agent",
        operation_id="operation-00001",
        fingerprint="fingerprint",
        outcome="succeeded",
        external_reference=receipt["external_reference"],
        destination_receipt_sha256=digest,
        readback_sha256=hashlib.sha256(canonical_readback_payload(proof)).hexdigest(),
    )
    return Reconciliation(store, trust_journal=trust), dict(
        agent_id="agent",
        operation_id="operation-00001",
        result="succeeded",
        external_reference=receipt["external_reference"],
        evidence_sha256=digest,
        reviewer="reviewer",
        destination_receipt=receipt,
        readback_attestation=proof,
        reviewer_signature_hex=reviewer.sign(canonical_review_payload(statement)).hex(),
        destination_key_id="old",
        observer_key_id="old",
    )


def test_registry_settlement_retains_signed_bundle_and_audit(configured, tmp_path, monkeypatch):
    store, *_ = configured
    reconciliation, kwargs = settlement_fixture(configured, tmp_path, monkeypatch)
    from src.governance.trust_sdk import verify_journaled_action_evidence

    evidence = dict(
        destination_receipt=kwargs["destination_receipt"],
        readback_attestation=kwargs["readback_attestation"],
        agent_id="agent",
        operation_id="operation-00001",
        fingerprint="fingerprint",
        outcome="succeeded",
        external_reference=kwargs["external_reference"],
    )
    assert (
        verify_journaled_action_evidence(
            trust_journal=configured[1], destination_key_id="old", observer_key_id="old", **evidence
        ).outcome
        == "succeeded"
    )
    with pytest.raises(ValueError, match="override"):
        verify_journaled_action_evidence(
            trust_journal=configured[1],
            destination_key_id="old",
            observer_key_id="old",
            destination_key_hex="00" * 32,
            **evidence,
        )
    assert reconciliation.record(**kwargs)["state"] == "succeeded"
    records = store.load_audit()
    assert AuditLog.verify_chain(records)
    metadata = json.loads(records[-1]["reason"])
    row = store._db.execute("SELECT bundle FROM reconciliation_evidence").fetchone()
    assert hashlib.sha256(row["bundle"].encode()).hexdigest() == metadata["evidence_bundle_sha256"]
    assert json.loads(row["bundle"])["reviewer_signature_hex"] == kwargs["reviewer_signature_hex"]
    assert metadata["trust_context"]["readback_revision"] == 1
    assert store.get_budget("agent")["spent"] == 2
    with pytest.raises(ReconciliationError):
        reconciliation.record(**kwargs)
    assert len(store.load_audit()) == 1


def test_failed_audit_insert_rolls_back_operation_budget_and_evidence(configured, tmp_path, monkeypatch):
    store, *_ = configured
    reconciliation, kwargs = settlement_fixture(configured, tmp_path, monkeypatch)
    if isinstance(store, SqliteStore):
        store._db.execute(
            "CREATE TRIGGER deny_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END"
        )
        expected_error = sqlite3.IntegrityError
    else:
        import psycopg

        store._db.execute(
            "CREATE FUNCTION deny_audit() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'injected audit failure'; END; $$"
        )
        store._db.execute("CREATE TRIGGER deny_audit BEFORE INSERT ON audit FOR EACH ROW EXECUTE FUNCTION deny_audit()")
        expected_error = psycopg.errors.RaiseException
    before = store.get_budget("agent")
    with pytest.raises(expected_error, match="injected audit failure"):
        reconciliation.record(**kwargs)
    assert OperationLedger(store).get("agent", "operation-00001")["state"] == "unknown"
    assert store.get_budget("agent") == before
    assert store._db.execute("SELECT count(*) AS n FROM operation_reconciliations").fetchone()["n"] == 0


def test_two_publishers_cannot_fork_same_revision(configured):
    store, trust, controllers, _, envelopes, pinned = configured
    if isinstance(store, SqliteStore):
        other = SqliteStore(store._db.execute("PRAGMA database_list").fetchone()["file"])
    else:
        from psycopg.conninfo import make_conninfo

        other = PostgresStore(make_conninfo(os.environ["AGENTBRIDGE_TEST_PG"], options=store._db.info.options))
    try:
        second = SigningTrustJournal(other, controller_keys=pinned)
        proposals = []
        for name in ("candidate-a", "candidate-b"):
            new = dict(
                key_id=name,
                public_key_hex=public(Ed25519PrivateKey.generate()),
                state="staged",
            )
            proposals.append(
                signed_registry(
                    controllers["readback"],
                    "readback",
                    2,
                    envelopes["readback"],
                    envelopes["readback"]["keys"] + [new],
                )
            )

        def publish(item):
            journal, proposal = item
            try:
                journal.publish(proposal)
                return True
            except TrustJournalDenied:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(publish, zip((trust, second), proposals))) == [
                False,
                True,
            ]
        assert resolve(trust)["readback_revision"] == 2
    finally:
        other.close()


def test_staged_key_cannot_be_selected_or_overridden_by_environment(configured, tmp_path, monkeypatch):
    store, trust, controllers, signer, envelopes, _ = configured
    reconciliation, kwargs = settlement_fixture(configured, tmp_path, monkeypatch)
    old = dict(envelopes["readback"]["keys"][0])
    new = dict(
        key_id="staged",
        public_key_hex=public(Ed25519PrivateKey.generate()),
        state="staged",
    )
    trust.publish(signed_registry(controllers["readback"], "readback", 2, envelopes["readback"], [old, new]))
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", public(signer["readback"]))
    with pytest.raises(ReconciliationError, match="trust policy"):
        reconciliation.record(**dict(kwargs, observer_key_id="staged"))
    assert OperationLedger(store).get("agent", "operation-00001")["state"] == "unknown"


@pytest.mark.parametrize("domain", ["destination", "readback"])
def test_revoked_signers_fail_even_with_legacy_environment_keys(configured, tmp_path, monkeypatch, domain):
    store, trust, controllers, signer, envelopes, _ = configured
    reconciliation, kwargs = settlement_fixture(configured, tmp_path, monkeypatch)
    old = dict(envelopes[domain]["keys"][0])
    replacement = dict(key_id="replacement", public_key_hex=public(Ed25519PrivateKey.generate()), state="staged")
    staged = signed_registry(controllers[domain], domain, 2, envelopes[domain], [old, replacement])
    trust.publish(staged)
    old["state"], replacement["state"] = "revoked", "active"
    trust.publish(signed_registry(controllers[domain], domain, 3, staged, [old, replacement]))
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", public(signer["destination"]))
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", public(signer["readback"]))
    with pytest.raises(ReconciliationError, match="trust policy"):
        reconciliation.record(**kwargs)
    assert OperationLedger(store).get("agent", "operation-00001")["state"] == "unknown"
    assert store.get_budget("agent")["reserved"]


def test_rotation_serializes_with_settlement_commit(configured, tmp_path, monkeypatch):
    store, trust, controllers, _, envelopes, pinned = configured
    reconciliation, kwargs = settlement_fixture(configured, tmp_path, monkeypatch)
    if isinstance(store, SqliteStore):
        other = SqliteStore(store._db.execute("PRAGMA database_list").fetchone()["file"])
    else:
        from psycopg.conninfo import make_conninfo

        other = PostgresStore(make_conninfo(os.environ["AGENTBRIDGE_TEST_PG"], options=store._db.info.options))
    try:
        second = SigningTrustJournal(other, controller_keys=pinned)
        added = dict(key_id="replacement", public_key_hex=public(Ed25519PrivateKey.generate()), state="staged")
        proposal = signed_registry(
            controllers["readback"], "readback", 2, envelopes["readback"], envelopes["readback"]["keys"] + [added]
        )
        entered, release = Event(), Event()
        original = reconciliation._append_settlement_evidence

        def paused(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError("settlement barrier timed out")
            return original(*args, **kwargs)

        monkeypatch.setattr(reconciliation, "_append_settlement_evidence", paused)
        with ThreadPoolExecutor(max_workers=2) as pool:
            settlement = pool.submit(reconciliation.record, **kwargs)
            try:
                assert entered.wait(5)
                rotation = pool.submit(second.publish, proposal)
                with pytest.raises(FutureTimeout):
                    rotation.result(timeout=0.1)
            finally:
                release.set()
            assert settlement.result(timeout=10)["state"] == "succeeded"
            assert rotation.result(timeout=10)
        assert resolve(trust)["readback_revision"] == 2
    finally:
        other.close()


@pytest.mark.parametrize("bad_id", [None, [], 1, True])
def test_malformed_identity_fails_as_policy_denial(bad_id):
    with pytest.raises(ObserverKeyDenied):
        ObserverTrustRegistry([ObserverKey(bad_id, public(Ed25519PrivateKey.generate()), "active")])


def test_complete_synthetic_acceptance_workflow():
    result = run_qualification()
    assert result["passed"] and len(result["checks"]) == 12
    assert not result["independent_custody"] and not result["production_qualified"]
