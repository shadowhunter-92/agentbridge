"""Negative contracts for the end-to-end Trust/Evidence synthetic flow."""
import pytest
from examples.trust_evidence_end_to_end import run_synthetic_flow


def test_complete_approved_synthetic_action(tmp_path):
    result = run_synthetic_flow(tmp_path)
    for field in ("approved_request_bound_to_target", "durable_unknown_before_reconciliation",
                  "lost_ack_detected", "duplicate_destination_effect_denied",
                  "duplicate_ledger_claim_denied", "signed_destination_receipt_valid",
                  "registered_separate_observer_signature_valid", "verified_audit_checkpoint"):
        assert result[field] is True
    assert result["reconciled_state"] == "succeeded"
    assert result["external_production_truth_verified"] is False


def test_denied_approval_does_not_touch_destination(tmp_path):
    with pytest.raises(PermissionError, match="human approval denied"):
        run_synthetic_flow(tmp_path, approve=False)
    assert not (tmp_path / "target.sqlite3").exists()


def test_missing_readback_preserves_unknown_and_prevents_replay(tmp_path):
    from src.governance.store import SqliteStore
    from src.governance.operation_ledger import OperationLedger, OperationConflict
    from src.governance.sandbox_readback import ObservationUnavailable
    with pytest.raises(ObservationUnavailable):
        run_synthetic_flow(tmp_path, allow_readback=False)
    store = SqliteStore(str(tmp_path / "control.sqlite3"))
    try:
        record = OperationLedger(store).get("synthetic-agent", "synthetic-operation-001")
        assert record["state"] == "unknown"
        with pytest.raises(OperationConflict):
            OperationLedger(store).claim("synthetic-agent", "synthetic-operation-001", record["fingerprint"])
    finally:
        store.close()
