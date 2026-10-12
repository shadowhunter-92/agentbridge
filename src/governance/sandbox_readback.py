"""Authoritative *sandbox* target and separate read-only state observer.

Reproducible proof of the control flow after a committed side effect with lost
acknowledgment. This is not a general-purpose real-target adapter or production
authentication boundary. Target and observer must run under separate principals
and trust roots in an actual deployment.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .destination_receipts import (
    canonical_receipt_payload, verify_destination_receipt, UntrustedReceipt,
)
from .readback_attestations import canonical_readback_payload


class SandboxConflict(RuntimeError):
    """A second write attempted to reuse a durable operation identity."""


class ObservationUnavailable(RuntimeError):
    """Remote state cannot be established; never settle as failed by absence."""


def _json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _check_id(value):
    return isinstance(value, str) and bool(value) and len(value) <= 256


class SandboxTarget:
    """Sandbox write authority. The target signs and stores its own receipt.

    Only the target constructor receives its signing callback. It deliberately
    exposes no method that mutates or signs the observer's readback statement.
    """
    def __init__(self, path: str, *, sign):
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("durable sandbox target database required")
        if not callable(sign):
            raise ValueError("destination signer required")
        self._sign = sign
        self._db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS sandbox_effects("
            "agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
            "fingerprint TEXT NOT NULL, outcome TEXT NOT NULL, "
            "external_reference TEXT NOT NULL, receipt_json TEXT NOT NULL, "
            "PRIMARY KEY(agent_id,operation_id))"
        )

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def commit(self, *, agent_id: str, operation_id: str,
               fingerprint: str, lose_ack: bool = False) -> dict:
        if not all(_check_id(item) for item in (agent_id, operation_id, fingerprint)):
            raise ValueError("invalid sandbox operation identity")
        external_reference = "sandbox-effect:" + operation_id
        receipt = dict(agent_id=agent_id, operation_id=operation_id,
                       fingerprint=fingerprint, outcome="succeeded",
                       external_reference=external_reference)
        signature = self._sign(canonical_receipt_payload(receipt))
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise ValueError("invalid destination signer output")
        receipt["signature_hex"] = signature.hex()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._db.execute(
                "SELECT 1 FROM sandbox_effects WHERE agent_id=? AND operation_id=?",
                (agent_id, operation_id)).fetchone()
            if existing:
                raise SandboxConflict("sandbox operation already executed; no replay")
            self._db.execute(
                "INSERT INTO sandbox_effects VALUES(?,?,?,?,?,?)",
                (agent_id, operation_id, fingerprint, "succeeded",
                 external_reference, _json(receipt)),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        if lose_ack:
            raise TimeoutError("simulated lost acknowledgement after committed sandbox action")
        return receipt


class SandboxReadOnlyObserver:
    """Independent SQL connection, explicitly opened read-only.

    The signer and database read credentials MUST be provisioned independently
    in deployment. The observer checks authoritative sandbox state and verifies
    the destination signature before issuing its separate attestation.
    """
    def __init__(self, path: str, *, destination_public_key_hex: str, sign):
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("durable sandbox state path required")
        if not callable(sign):
            raise ValueError("separate readback signer required")
        self._sign = sign
        self._destination_public_key_hex = destination_public_key_hex
        # URI mode=ro disallows modifications through this connection.
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        self._db = sqlite3.connect(uri, uri=True, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA query_only=ON")

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def observe(self, *, agent_id: str, operation_id: str, fingerprint: str):
        if not all(_check_id(item) for item in (agent_id, operation_id, fingerprint)):
            raise ObservationUnavailable("operation identity required")
        try:
            row = self._db.execute(
                "SELECT agent_id,operation_id,fingerprint,outcome,"
                "external_reference,receipt_json FROM sandbox_effects "
                "WHERE agent_id=? AND operation_id=?",
                (agent_id, operation_id)).fetchone()
        except sqlite3.Error as exc:
            raise ObservationUnavailable("authoritative sandbox state unavailable") from exc
        if row is None:
            # Absence is ambiguous: never issue a signed failed outcome here.
            raise ObservationUnavailable("no authoritative committed record; outcome unknown")
        record = dict(row)
        if record["fingerprint"] != fingerprint or record["outcome"] != "succeeded":
            raise ObservationUnavailable("authoritative state disagrees with operation")
        try:
            receipt = json.loads(record.pop("receipt_json"))
            digest = verify_destination_receipt(
                receipt, agent_id=agent_id, operation_id=operation_id,
                fingerprint=fingerprint,
                trusted_public_key_hex=self._destination_public_key_hex)
        except (ValueError, TypeError, UntrustedReceipt) as exc:
            raise ObservationUnavailable("destination state receipt untrusted") from exc
        if (receipt["outcome"] != record["outcome"]
                or receipt["external_reference"] != record["external_reference"]):
            raise ObservationUnavailable("destination receipt disagrees with persisted state")
        source_digest = hashlib.sha256(_json({**record, "receipt": receipt}).encode()).hexdigest()
        proof = {
            "agent_id": agent_id,
            "operation_id": operation_id,
            "fingerprint": fingerprint,
            "outcome": record["outcome"],
            "external_reference": record["external_reference"],
            "observed_at": int(time.time()),
            "source": "sandbox:read-only-authoritative-sql-v1",
            "source_evidence_sha256": source_digest,
            "destination_receipt_sha256": digest,
        }
        signature = self._sign(canonical_readback_payload(proof))
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise ObservationUnavailable("readback signer did not issue valid signature")
        proof["signature_hex"] = signature.hex()
        return receipt, proof
