"""Destination-enforced SQLite epoch test, replay and independent readback."""
import time
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from src.governance.fenced_sqlite_destination import (
    FencedSqliteTarget, SqliteFenceDenied, SqliteDuplicateEffect
)
from src.governance.sandbox_readback import SandboxReadOnlyObserver
from src.governance.trust_sdk import verify_action_evidence


def _public(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def test_fenced_sqlite_target_handover_and_lost_ack(tmp_path):
    path = str(tmp_path / "fenced-target.sqlite")
    writer = Ed25519PrivateKey.generate()
    observer_signer = Ed25519PrivateKey.generate()
    with FencedSqliteTarget(path, sign=writer.sign) as old, FencedSqliteTarget(
        path, sign=writer.sign
    ) as promoted:
        epoch = old.acquire(scope="scope", owner="old", ttl_seconds=1)
        with pytest.raises(SqliteFenceDenied):
            promoted.acquire(scope="scope", owner="new", ttl_seconds=20)
        with pytest.raises(TimeoutError, match="acknowledgement dropped"):
            old.commit(scope="scope", owner="old", epoch=epoch,
                       agent_id="agent", operation_id="first",
                       fingerprint="approved", lose_ack=True)
        with pytest.raises(SqliteDuplicateEffect):
            old.commit(scope="scope", owner="old", epoch=epoch,
                       agent_id="agent", operation_id="first",
                       fingerprint="approved")
        with SandboxReadOnlyObserver(
            path, destination_public_key_hex=_public(writer),
            sign=observer_signer.sign
        ) as ro:
            receipt, attestation = ro.observe(
                agent_id="agent", operation_id="first", fingerprint="approved")
            verified = verify_action_evidence(
                destination_receipt=receipt, readback_attestation=attestation,
                agent_id="agent", operation_id="first",
                fingerprint="approved", outcome="succeeded",
                external_reference=receipt["external_reference"],
                destination_key_hex=_public(writer),
                readback_key_hex=_public(observer_signer),
            )
            assert verified.outcome == "succeeded"
        # Real expiry uses destination database time, not a caller-provided value.
        time.sleep(1.2)
        new_epoch = promoted.acquire(scope="scope", owner="new", ttl_seconds=15)
        assert new_epoch > epoch
        with pytest.raises(SqliteFenceDenied):
            old.commit(scope="scope", owner="old", epoch=epoch,
                       agent_id="agent", operation_id="stale",
                       fingerprint="approved")
        newer = promoted.commit(
            scope="scope", owner="new", epoch=new_epoch,
            agent_id="agent", operation_id="second", fingerprint="approved")
        assert newer["outcome"] == "succeeded"
        assert promoted.db.execute(
            "SELECT count(*) FROM sandbox_effects WHERE operation_id='stale'"
        ).fetchone()[0] == 0


def test_fenced_sqlite_rejects_untrusted_epoch(tmp_path):
    key = Ed25519PrivateKey.generate()
    with FencedSqliteTarget(str(tmp_path / "f.sqlite"), sign=key.sign) as target:
        epoch = target.acquire(scope="scope", owner="old")
        for invalid in (True, 0, -1, 1.3):
            with pytest.raises(ValueError):
                target.commit(scope="scope", owner="old", epoch=invalid,
                              agent_id="a", operation_id="o", fingerprint="f")
        with pytest.raises(SqliteFenceDenied):
            target.commit(scope="scope", owner="other", epoch=epoch,
                          agent_id="a", operation_id="o", fingerprint="f")
