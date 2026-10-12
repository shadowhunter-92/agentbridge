"""Restoring a prior governance backup must be detected against separately kept witness state.

Disposable SQLite test; this is not a managed PostgreSQL/PITR or HA drill.
"""
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.governance.audit import AuditLog
from src.governance.external_anchor import AnchorVerificationError, create_witness_statement
from src.governance.identity import AgentIdentity
from src.governance.store import SqliteStore
from src.governance.witness_journal import WitnessJournal


def _pub(key):
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()


def _record(audit):
    audit.record(actor="backup-test", action="route_call", source_protocol="mcp",
                 target_protocol="mcp", capability="read", decision="allow")


def test_restored_old_governance_database_rejected_by_separate_witness(tmp_path):
    live = str(tmp_path / "live.sqlite")
    older_backup = str(tmp_path / "older.sqlite")
    journal_path = str(tmp_path / "witness.sqlite")
    issuer = AgentIdentity.generate("audit-issuer")
    witness_signer = Ed25519PrivateKey.generate()
    opts = dict(checkpoint_key_hex=issuer.public_key_hex,
                witness_key_hex=_pub(witness_signer), witness_id="separate-operator")
    with WitnessJournal(journal_path, **opts) as witness:
        store = SqliteStore(live)
        try:
            audit = AuditLog(store)
            _record(audit)
            cp1 = audit.checkpoint(issuer.sign, issuer.public_key_hex)
            proof1 = create_witness_statement(cp1, witness_id=opts["witness_id"],
                                             witnessed_at="2026-10-12T00:00:00Z",
                                             anchor_reference="test://separate-journal/1",
                                             sign=witness_signer.sign)
            witness.accept(store.load_audit(), cp1, proof1)
            # Take a real SQL-consistent snapshot *before* the new trusted head.
            with sqlite3.connect(older_backup) as snapshot:
                store._db.backup(snapshot)
            _record(audit)
            cp2 = audit.checkpoint(issuer.sign, issuer.public_key_hex)
            proof2 = create_witness_statement(cp2, witness_id=opts["witness_id"],
                                             witnessed_at="2026-10-12T00:01:00Z",
                                             anchor_reference="test://separate-journal/2",
                                             sign=witness_signer.sign)
            witness.accept(store.load_audit(), cp2, proof2)
            assert witness.latest()["checkpoint"] == cp2
        finally:
            store.close()
        # Restore ONLY governance data, not the separately administered journal.
        with sqlite3.connect(older_backup) as backup:
            with sqlite3.connect(live) as restored:
                backup.backup(restored)
        restored_store = SqliteStore(live)
        try:
            with pytest.raises(AnchorVerificationError, match="truncated|rolled back"):
                witness.accept(restored_store.load_audit(), cp2, proof2)
            with pytest.raises(AnchorVerificationError, match="rollback"):
                witness.accept(restored_store.load_audit(), cp1, proof1)
        finally:
            restored_store.close()
