"""Authoritative *sandbox* target and separate read-only state observer.

Reproducible proof of the control flow after a committed side effect with lost
acknowledgment. This is not a general-purpose real-target adapter or production
authentication boundary. Target and observer must run under separate principals
and trust roots in an actual deployment.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from .destination_receipts import (
    UntrustedReceipt,
    canonical_receipt_payload,
    verify_destination_receipt,
    verify_queued_authorization,
    verify_queued_destination_receipt,
)
from .queued_destination_contract import (
    MAX_ACTION_BYTES,
    MAX_AUTHORIZATION_BYTES,
    MAX_RECEIPT_BYTES,
    MAX_RESULT_BYTES,
    canonical_queued_json,
    normalize_queued_descriptor,
)
from .readback_attestations import (
    QUEUED_READBACK_SOURCE,
    canonical_queued_readback_payload,
    canonical_readback_payload,
    queued_source_evidence_sha256,
    verify_queued_readback_attestation,
)


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
        if self._db.execute("SELECT 1 FROM main.sqlite_master WHERE name LIKE 'ab_queued_%'").fetchone():
            self._db.close()
            raise ValueError("queued-only destination file rejects the v1 sandbox contract")
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
        if self._db.execute("SELECT 1 FROM main.sqlite_master WHERE name LIKE 'ab_queued_%'").fetchone():
            raise ValueError("queued-only destination file rejects the v1 sandbox contract")
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
        self._path = Path(path).resolve()
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

    def observe_queued(self, authorization, action_bytes, descriptor):
        """Read exact committed v2 state through this separate read-only handle.

        Missing, malformed and oversized state produces no signed failed proof.
        An expired execution authorization remains useful only for observation.
        """
        from .fenced_sqlite_destination import _qualify_queued_destination

        try:
            descriptor = normalize_queued_descriptor(descriptor)
            if (self._path != Path(descriptor["path"]).resolve()
                    or descriptor["destination_public_key_hex"] != self._destination_public_key_hex):
                raise ObservationUnavailable("observer does not bind the configured queued destination")
            authorization_digest = verify_queued_authorization(
                authorization, descriptor=descriptor, action_bytes=action_bytes)
            authorization = json.loads(canonical_queued_json(authorization))
            self._db.execute("BEGIN")
            try:
                _qualify_queued_destination(self._db, descriptor)
                lengths = self._db.execute(
                    "SELECT length(action_bytes),length(CAST(authorization_json AS BLOB)),"
                    "length(CAST(result_json AS BLOB)),length(CAST(receipt_json AS BLOB)) "
                    "FROM main.ab_queued_effects_v2 WHERE tenant_id=? AND agent_id=? AND operation_id=?",
                    (authorization["tenant_id"], authorization["agent_id"], authorization["operation_id"]),
                ).fetchone()
                if lengths is None:
                    raise ObservationUnavailable("no authoritative queued record; outcome unknown")
                if any(type(size) is not int or not 1 <= size <= limit for size, limit in zip(
                    lengths, (MAX_ACTION_BYTES, MAX_AUTHORIZATION_BYTES, MAX_RESULT_BYTES, MAX_RECEIPT_BYTES),
                )):
                    raise ObservationUnavailable("authoritative queued record exceeds bounds")
                record = dict(self._db.execute(
                    "SELECT * FROM main.ab_queued_effects_v2 WHERE tenant_id=? AND agent_id=? AND operation_id=?",
                    (authorization["tenant_id"], authorization["agent_id"], authorization["operation_id"]),
                ).fetchone())
                receipt = json.loads(record["receipt_json"])
                result = json.loads(record["result_json"])
                if (record["authorization_json"] != canonical_queued_json(authorization).decode()
                        or record["action_bytes"] != action_bytes
                        or record["authorization_sha256"] != authorization_digest
                        or record["receipt_json"] != canonical_queued_json(receipt).decode()
                        or record["result_json"] != canonical_queued_json(result).decode()):
                    raise ObservationUnavailable("persisted queued authorization, action or encoding disagrees")
                receipt_digest = verify_queued_destination_receipt(
                    receipt, authorization=authorization, action_bytes=action_bytes, descriptor=descriptor, result=result)
                expected_record = {
                    **{name: authorization[name] for name in ("tenant_id", "agent_id", "operation_id", "fingerprint",
                                                             "attempt_id", "action_sha256", "fence_scope", "fence_owner", "fence_epoch")},
                    "authorization_sha256": authorization_digest, "result_sha256": receipt["result_sha256"],
                    "receipt_sha256": receipt_digest, "effect_id": result["effect_id"], "committed_at": receipt["committed_at"],
                }
                if any(record[name] != value for name, value in expected_record.items()):
                    raise ObservationUnavailable("queued committed record and signed receipt disagree")
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            proof = {name: receipt[name] for name in (
                "authorization_sha256", "tenant_id", "agent_id", "operation_id", "fingerprint", "target_id",
                "destination_id", "attempt_id", "fence_epoch", "action_sha256", "outcome", "external_reference",
                "committed_at", "result_sha256",
            )}
            proof.update({
                "domain": "agentbridge.queued-readback.v2", "destination_receipt_sha256": receipt_digest,
                "observed_at": int(time.time()), "source": QUEUED_READBACK_SOURCE,
                "observer_key_id": descriptor["observer_key_id"],
                "source_evidence_sha256": queued_source_evidence_sha256(
                    authorization=authorization, action_bytes=action_bytes, result=result, destination_receipt=receipt),
            })
            signature = self._sign(canonical_queued_readback_payload(proof))
            if not isinstance(signature, bytes) or len(signature) != 64:
                raise ObservationUnavailable("queued observer signer did not issue a valid signature")
            proof["signature_hex"] = signature.hex()
            verify_queued_readback_attestation(
                proof, authorization=authorization, action_bytes=action_bytes, descriptor=descriptor,
                result=result, destination_receipt=receipt)
            return result, receipt, proof
        except Exception as exc:
            if isinstance(exc, ObservationUnavailable):
                raise
            raise ObservationUnavailable("authoritative queued state is unavailable or untrusted") from exc
