"""End-to-end sandbox: committed effect, lost ACK, independent readback, SQL settlement."""
import hashlib
import sqlite3
from contextlib import closing

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.sandbox_readback import (
    SandboxTarget, SandboxReadOnlyObserver, SandboxConflict, ObservationUnavailable,
)
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger, OperationConflict
from src.governance.reconciliation import Reconciliation, ReconciliationError
from src.governance.budget import BudgetManager, Budget
from src.governance.destination_receipts import canonical_receipt_payload


def public(key):
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()


def test_committed_lost_ack_is_recovered_from_independent_readback(tmp_path, monkeypatch):
    target_key, observer_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    target_path = str(tmp_path / "authoritative-target.sqlite")
    ledger_path = str(tmp_path / "governance.sqlite")
    agent, op, fingerprint = "sandbox-agent", "sandbox-operation-00001", "sandbox-fingerprint"
    with SandboxTarget(target_path, sign=target_key.sign) as target:
        with closing(SqliteStore(ledger_path)) as store:
            budgets = BudgetManager(store)
            budgets.set_budget(agent, Budget(spend_limit=10))
            token, why = budgets.reserve(agent, 2)
            assert token, why
            OperationLedger(store).claim(agent, op, fingerprint, reservation_token=token)
            with pytest.raises(TimeoutError, match="lost acknowledgement"):
                target.commit(agent_id=agent, operation_id=op, fingerprint=fingerprint,
                              lose_ack=True)
            assert OperationLedger(store).get(agent, op)["state"] == "unknown"
            with pytest.raises(SandboxConflict):
                target.commit(agent_id=agent, operation_id=op, fingerprint=fingerprint)
            with pytest.raises(OperationConflict):
                OperationLedger(store).claim(agent, op, fingerprint)

            monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
            monkeypatch.setenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", public(target_key))
            monkeypatch.setenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", public(observer_key))
            with SandboxReadOnlyObserver(
                target_path, destination_public_key_hex=public(target_key),
                sign=observer_key.sign,
            ) as observer:
                receipt, proof = observer.observe(agent_id=agent, operation_id=op,
                                                  fingerprint=fingerprint)
                with pytest.raises(sqlite3.OperationalError):
                    observer._db.execute("DELETE FROM sandbox_effects")
                with pytest.raises(ObservationUnavailable):
                    observer.observe(agent_id=agent, operation_id="not-present",
                                     fingerprint=fingerprint)
                digest = hashlib.sha256(canonical_receipt_payload(receipt)).hexdigest()
                reconciliation = Reconciliation(store)
                kwargs = dict(agent_id=agent, operation_id=op, result="succeeded",
                              external_reference=receipt["external_reference"],
                              evidence_sha256=digest, reviewer="sandbox-operator",
                              destination_receipt=receipt)
                with pytest.raises(ReconciliationError, match="independent state-readback"):
                    reconciliation.record(**kwargs)
                with pytest.raises(ReconciliationError, match="untrusted independent"):
                    reconciliation.record(**kwargs, readback_attestation={
                        **proof, "source_evidence_sha256": "0" * 64})
                final = reconciliation.record(**kwargs, readback_attestation=proof)
                assert final["state"] == "succeeded"
                assert final["readback_sha256"]
                assert OperationLedger(store).get(agent, op)["state"] == "succeeded"
                assert store.get_budget(agent)["spent"] == 2
                assert store.get_budget(agent)["reserved"] == {}
                with pytest.raises(ReconciliationError):
                    reconciliation.record(**kwargs, readback_attestation=proof)
            assert target._db.execute("SELECT COUNT(*) FROM sandbox_effects").fetchone()[0] == 1


def test_observer_denies_unsigned_or_mismatched_authoritative_state(tmp_path):
    target_key, observer_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    target_path = str(tmp_path / "target.db")
    with SandboxTarget(target_path, sign=target_key.sign) as target:
        target.commit(agent_id="a", operation_id="operation-12345678", fingerprint="f")
        with SandboxReadOnlyObserver(target_path, destination_public_key_hex=public(target_key),
                                     sign=observer_key.sign) as observer:
            with pytest.raises(ObservationUnavailable):
                observer.observe(agent_id="a", operation_id="operation-12345678",
                                 fingerprint="different")
        target._db.execute("UPDATE sandbox_effects SET outcome='failed'")
        with SandboxReadOnlyObserver(target_path, destination_public_key_hex=public(target_key),
                                     sign=observer_key.sign) as observer:
            with pytest.raises(ObservationUnavailable):
                observer.observe(agent_id="a", operation_id="operation-12345678",
                                 fingerprint="f")
