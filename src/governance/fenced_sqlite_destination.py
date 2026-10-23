"""Experimental non-PostgreSQL destination with destination-side fencing.

A local SQLite *destination* serializes epoch validation and action insertion
in ONE BEGIN IMMEDIATE transaction. This does not fence an arbitrary SaaS API,
a replicated SQLite volume, or a target that does not call this destination.
Use only for disposable/supervised demonstrations.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

from .destination_receipts import (
    canonical_queued_receipt_payload,
    canonical_receipt_payload,
    verify_queued_authorization,
    verify_queued_destination_receipt,
)
from .queued_destination_contract import (
    QUEUED_RESULT_ENVELOPE_LIMIT_BYTES,
    canonical_queued_json,
    demo_result,
    normalize_queued_descriptor,
    queued_descriptor_sha256,
)


class SqliteFenceDenied(RuntimeError):
    """Lease is owned elsewhere, expired, or epoch no longer authoritative."""


class SqliteDuplicateEffect(RuntimeError):
    """An operation already reached the destination; never dispatch it again."""


def _identifier(value):
    return isinstance(value, str) and 1 <= len(value) <= 128


QUEUED_BINDING_TABLE = "ab_queued_destination_binding_v2"
QUEUED_EFFECT_TABLE = "ab_queued_effects_v2"
_QUEUED_TABLE_SQL = {
    "ab_destination_fences": (
        "CREATE TABLE ab_destination_fences (scope TEXT PRIMARY KEY, owner TEXT NOT NULL, "
        "epoch INTEGER NOT NULL, expires_seconds REAL NOT NULL)"
    ),
    QUEUED_BINDING_TABLE: (
        "CREATE TABLE ab_queued_destination_binding_v2 (singleton INTEGER NOT NULL PRIMARY KEY CHECK(singleton=1),"
        "version INTEGER NOT NULL CHECK(version=2),descriptor_json TEXT NOT NULL "
        "CHECK(length(CAST(descriptor_json AS BLOB)) BETWEEN 1 AND 8192),"
        "descriptor_sha256 TEXT NOT NULL CHECK(length(descriptor_sha256)=64),"
        "schema_sha256 TEXT NOT NULL CHECK(length(schema_sha256)=64))"
    ),
    QUEUED_EFFECT_TABLE: (
        "CREATE TABLE ab_queued_effects_v2 (tenant_id TEXT NOT NULL CHECK(length(tenant_id) BETWEEN 1 AND 128),"
        "agent_id TEXT NOT NULL CHECK(length(agent_id) BETWEEN 1 AND 128),"
        "operation_id TEXT NOT NULL CHECK(length(operation_id) BETWEEN 1 AND 128),"
        "authorization_sha256 TEXT NOT NULL CHECK(length(authorization_sha256)=64),"
        "fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),"
        "attempt_id TEXT NOT NULL CHECK(length(attempt_id) BETWEEN 1 AND 128),"
        "action_sha256 TEXT NOT NULL CHECK(length(action_sha256)=64),"
        "action_bytes BLOB NOT NULL CHECK(length(action_bytes) BETWEEN 1 AND 4096),"
        "authorization_json TEXT NOT NULL CHECK(length(CAST(authorization_json AS BLOB)) BETWEEN 1 AND 8192),"
        "result_json TEXT NOT NULL CHECK(length(CAST(result_json AS BLOB)) BETWEEN 1 AND 512),"
        "result_sha256 TEXT NOT NULL CHECK(length(result_sha256)=64),"
        "receipt_json TEXT NOT NULL CHECK(length(CAST(receipt_json AS BLOB)) BETWEEN 1 AND 16384),"
        "receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256)=64),"
        "effect_id TEXT NOT NULL CHECK(length(effect_id)=88),"
        "committed_at REAL NOT NULL CHECK(committed_at>0 AND committed_at<=253402300800),"
        "fence_scope TEXT NOT NULL CHECK(length(fence_scope) BETWEEN 1 AND 128),"
        "fence_owner TEXT NOT NULL CHECK(length(fence_owner) BETWEEN 1 AND 128),"
        "fence_epoch INTEGER NOT NULL CHECK(fence_epoch>=1),"
        "PRIMARY KEY(tenant_id,agent_id,operation_id),UNIQUE(tenant_id,attempt_id))"
    ),
}
_QUEUED_TRIGGER_SQL = {
    name: f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN "
          "SELECT RAISE(ABORT,'immutable queued destination record'); END"
    for table in (QUEUED_BINDING_TABLE, QUEUED_EFFECT_TABLE)
    for operation in ("UPDATE", "DELETE")
    for name in (table + "_deny_" + operation.lower(),)
}
_QUEUED_SCHEMA_SHA256 = hashlib.sha256(canonical_queued_json(
    {"tables": _QUEUED_TABLE_SQL, "triggers": _QUEUED_TRIGGER_SQL})).hexdigest()


def _qualify_queued_destination(db, descriptor):
    """Fail closed on partial/version-changed schemas and additional restrictions."""
    expected = {**_QUEUED_TABLE_SQL, **_QUEUED_TRIGGER_SQL}
    rows = db.execute("SELECT name,type,sql FROM main.sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    if {row["name"] for row in rows} != set(expected):
        raise ValueError("partial, unqualified or unexpected queued destination schema")
    for row in rows:
        if row["type"] != ("table" if row["name"] in _QUEUED_TABLE_SQL else "trigger") or row["sql"] != expected[row["name"]]:
            raise ValueError("unsupported queued destination schema definition")
    # Autoindexes are omitted above. Confirm exactly the declared primary and
    # unique keys; an added UNIQUE restriction is not an equivalent schema.
    for table, key_columns in (
        ("ab_destination_fences", {("scope",)}),
        (QUEUED_BINDING_TABLE, set()),
        (QUEUED_EFFECT_TABLE, {("tenant_id", "agent_id", "operation_id"), ("tenant_id", "attempt_id")}),
    ):
        indexes = db.execute(f"PRAGMA main.index_list('{table}')").fetchall()
        actual = set()
        for index in indexes:
            if not index["unique"] or index["partial"] or index["origin"] not in ("pk", "u"):
                raise ValueError("unsupported queued destination index")
            columns = tuple(item["name"] for item in db.execute(f"PRAGMA main.index_info('{index['name']}')"))
            actual.add(columns)
        if actual != key_columns or len(indexes) != len(key_columns):
            raise ValueError("unexpected queued destination uniqueness restrictions")
    bounds = db.execute(
        "SELECT singleton,version,length(CAST(descriptor_json AS BLOB)) AS descriptor_bytes,"
        "length(descriptor_sha256) AS descriptor_digest_bytes,length(schema_sha256) AS schema_digest_bytes "
        "FROM main.ab_queued_destination_binding_v2"
    ).fetchall()
    if (len(bounds) != 1 or bounds[0]["singleton"] != 1 or bounds[0]["version"] != 2
            or type(bounds[0]["descriptor_bytes"]) is not int or not 1 <= bounds[0]["descriptor_bytes"] <= 8192
            or bounds[0]["descriptor_digest_bytes"] != 64 or bounds[0]["schema_digest_bytes"] != 64):
        raise ValueError("queued destination binding is missing, oversized or unsupported")
    rows = db.execute("SELECT * FROM main.ab_queued_destination_binding_v2").fetchall()
    if (rows[0]["singleton"] != 1 or rows[0]["version"] != 2
            or rows[0]["descriptor_json"] != canonical_queued_json(descriptor).decode()
            or rows[0]["descriptor_sha256"] != queued_descriptor_sha256(descriptor)
            or rows[0]["schema_sha256"] != _QUEUED_SCHEMA_SHA256):
        raise ValueError("queued destination binding is missing, changed or unsupported")


class FencedSqliteTarget:
    def __init__(self, path: str, *, sign, queued_descriptor=None):
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("single durable disposable SQLite destination required")
        if not callable(sign):
            raise ValueError("destination-controlled signing callback required")
        self.sign = sign
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self._queued_descriptor = None
        try:
            if queued_descriptor is not None:
                descriptor = normalize_queued_descriptor(queued_descriptor)
                if Path(path).resolve() != Path(descriptor["path"]).resolve():
                    raise ValueError("queued descriptor does not bind this exact destination file")
                self._queued_descriptor = descriptor
                self.db.execute("PRAGMA busy_timeout=" + str(max(1, math.ceil(descriptor["call_timeout_seconds"] * 1000))))
                self._initialize_queued()
                return
            if self.db.execute("SELECT 1 FROM main.sqlite_master WHERE name LIKE 'ab_queued_%'").fetchone():
                raise ValueError("queued-only destination file rejects v1 target access")
            self._initialize_v1()
        except BaseException:
            self.db.close()
            raise

    def _initialize_v1(self):
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS ab_destination_fences "
            "(scope TEXT PRIMARY KEY, owner TEXT NOT NULL, epoch INTEGER NOT NULL, "
            "expires_seconds REAL NOT NULL)"
        )
        # Reuse the sandbox observer's read-only, signed readback contract.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sandbox_effects "
            "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
            "fingerprint TEXT NOT NULL, outcome TEXT NOT NULL, "
            "external_reference TEXT NOT NULL, receipt_json TEXT NOT NULL, "
            "PRIMARY KEY(agent_id,operation_id))"
        )

    def _initialize_queued(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            rows = self.db.execute("SELECT name FROM main.sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if not rows:
                for statement in _QUEUED_TABLE_SQL.values():
                    self.db.execute(statement)
                self.db.execute("INSERT INTO main.ab_queued_destination_binding_v2 VALUES(1,2,?,?,?)", (
                    canonical_queued_json(self._queued_descriptor).decode(),
                    queued_descriptor_sha256(self._queued_descriptor), _QUEUED_SCHEMA_SHA256,
                ))
                for statement in _QUEUED_TRIGGER_SQL.values():
                    self.db.execute(statement)
            _qualify_queued_destination(self.db, self._queued_descriptor)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def acquire(self, *, scope: str, owner: str, ttl_seconds: int = 15) -> int:
        if not _identifier(scope) or not _identifier(owner):
            raise ValueError("bounded scope and owner required")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("bounded integer TTL required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            now = self.db.execute("SELECT (julianday('now') - 2440587.5) * 86400.0").fetchone()[0]
            row = self.db.execute(
                "SELECT epoch,expires_seconds FROM ab_destination_fences WHERE scope=?",
                (scope,),
            ).fetchone()
            if row is not None and row["expires_seconds"] > now:
                raise SqliteFenceDenied("an authoritative destination owner is already live")
            epoch = (row["epoch"] + 1) if row else 1
            self.db.execute(
                "INSERT INTO ab_destination_fences(scope,owner,epoch,expires_seconds) "
                "VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET "
                "owner=excluded.owner,epoch=excluded.epoch,"
                "expires_seconds=excluded.expires_seconds",
                (scope, owner, epoch, now + ttl_seconds),
            )
            self.db.execute("COMMIT")
            return epoch
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def commit(
        self, *, scope: str, owner: str, epoch: int,
        agent_id: str, operation_id: str, fingerprint: str,
        lose_ack: bool = False,
    ):
        if self._queued_descriptor is not None or self.db.execute(
            "SELECT 1 FROM main.sqlite_master WHERE name LIKE 'ab_queued_%'"
        ).fetchone():
            raise ValueError("queued-only destination rejects the v1 commit contract")
        if not all(_identifier(x) for x in (scope, owner, agent_id, operation_id, fingerprint)):
            raise ValueError("exact bounded operation identity required")
        if type(epoch) is not int or epoch < 1:
            raise ValueError("valid monotonic destination epoch required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT owner,epoch,expires_seconds, "
                "(julianday('now') - 2440587.5) * 86400.0 AS now_seconds "
                "FROM ab_destination_fences WHERE scope=?",
                (scope,),
            ).fetchone()
            if (row is None or row["owner"] != owner or row["epoch"] != epoch
                    or row["expires_seconds"] <= row["now_seconds"]):
                raise SqliteFenceDenied("stale, expired or unauthorized destination epoch")
            if self.db.execute(
                "SELECT 1 FROM sandbox_effects WHERE agent_id=? AND operation_id=?",
                (agent_id, operation_id),
            ).fetchone():
                raise SqliteDuplicateEffect("operation was already executed at the destination")
            receipt = {
                "agent_id": agent_id,
                "operation_id": operation_id,
                "fingerprint": fingerprint,
                "outcome": "succeeded",
                "external_reference": "sqlite-fenced-effect:" + operation_id,
            }
            signature = self.sign(canonical_receipt_payload(receipt))
            if not isinstance(signature, bytes) or len(signature) != 64:
                raise ValueError("destination signature invalid")
            receipt["signature_hex"] = signature.hex()
            self.db.execute(
                "INSERT INTO sandbox_effects VALUES(?,?,?,?,?,?)",
                (agent_id, operation_id, fingerprint, "succeeded",
                 receipt["external_reference"],
                 json.dumps(receipt, sort_keys=True, separators=(",", ":"))),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        if lose_ack:
            raise TimeoutError("committed SQLite destination effect; acknowledgement dropped")
        return receipt

    def commit_queued(self, authorization, action_bytes, lose_ack=False):
        """One action, accepted and committed under its destination fence lock.

        A duplicate always refuses; it is not an automatic replay contract.
        Recovery reads the committed record using the independent observer.
        """
        if self._queued_descriptor is None:
            raise ValueError("queued-only operator destination configuration required")
        descriptor = self._queued_descriptor
        # Cheap bounded structural/signature validation before a bounded wait.
        # This historical check alone never permits the effect below.
        verify_queued_authorization(authorization, descriptor=descriptor, action_bytes=action_bytes)
        # Freeze caller-owned mappings before using the validated values.
        authorization = json.loads(canonical_queued_json(authorization))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            _qualify_queued_destination(self.db, descriptor)
            row = self.db.execute(
                "SELECT owner,epoch,expires_seconds,(julianday('now') - 2440587.5) * 86400.0 AS now_seconds "
                "FROM main.ab_destination_fences WHERE scope=?", (authorization["fence_scope"],)
            ).fetchone()
            if row is None:
                raise SqliteFenceDenied("missing authoritative queued destination fence")
            # The SQL clock is evaluated only after BEGIN IMMEDIATE waited.
            authorization_digest = verify_queued_authorization(
                authorization, descriptor=descriptor, action_bytes=action_bytes, now=row["now_seconds"])
            if (row["owner"] != authorization["fence_owner"] or row["epoch"] != authorization["fence_epoch"]
                    or row["expires_seconds"] <= row["now_seconds"]
                    or authorization["expires_at"] > row["expires_seconds"]):
                raise SqliteFenceDenied("stale, expired or unauthorized queued destination fence")
            if authorization["result_limit_bytes"] < QUEUED_RESULT_ENVELOPE_LIMIT_BYTES:
                raise ValueError("immutable result allowance cannot hold bounded queued evidence")
            if self.db.execute(
                "SELECT 1 FROM main.ab_queued_effects_v2 WHERE tenant_id=? AND "
                "((agent_id=? AND operation_id=?) OR attempt_id=?)",
                (authorization["tenant_id"], authorization["agent_id"], authorization["operation_id"], authorization["attempt_id"]),
            ).fetchone():
                raise SqliteDuplicateEffect("queued operation or attempt already executed; no replay")
            result = demo_result(action_bytes, authorization_digest)
            result_raw = canonical_queued_json(result)
            receipt = {
                "domain": "agentbridge.queued-receipt.v2", "authorization_sha256": authorization_digest,
                **{name: authorization[name] for name in ("tenant_id", "agent_id", "operation_id", "fingerprint",
                                                         "target_id", "destination_id", "attempt_id", "fence_epoch", "action_sha256")},
                "outcome": "succeeded", "external_reference": result["effect_id"],
                "committed_at": row["now_seconds"], "result_sha256": hashlib.sha256(result_raw).hexdigest(),
                "destination_key_id": descriptor["destination_key_id"],
            }
            signature = self.sign(canonical_queued_receipt_payload(receipt))
            if not isinstance(signature, bytes) or len(signature) != 64:
                raise ValueError("destination signature invalid")
            receipt["signature_hex"] = signature.hex()
            receipt_digest = verify_queued_destination_receipt(
                receipt, authorization=authorization, action_bytes=action_bytes, descriptor=descriptor, result=result)
            # A provisioned signer is a callback and may consume the remaining
            # execution window. Sample destination time again after signing,
            # immediately before the effect INSERT under this same write lock.
            current = self.db.execute(
                "SELECT owner,epoch,expires_seconds,(julianday('now') - 2440587.5) * 86400.0 AS now_seconds "
                "FROM main.ab_destination_fences WHERE scope=?", (authorization["fence_scope"],)
            ).fetchone()
            if (current is None or current["owner"] != authorization["fence_owner"]
                    or current["epoch"] != authorization["fence_epoch"]
                    or current["expires_seconds"] <= current["now_seconds"]
                    or authorization["expires_at"] > current["expires_seconds"]):
                raise SqliteFenceDenied("queued destination fence expired or changed while signing")
            verify_queued_authorization(
                authorization, descriptor=descriptor, action_bytes=action_bytes, now=current["now_seconds"])
            self.db.execute(
                "INSERT INTO main.ab_queued_effects_v2 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    authorization["tenant_id"], authorization["agent_id"], authorization["operation_id"],
                    authorization_digest, authorization["fingerprint"], authorization["attempt_id"],
                    authorization["action_sha256"], action_bytes, canonical_queued_json(authorization).decode(),
                    result_raw.decode(), receipt["result_sha256"], canonical_queued_json(receipt).decode(), receipt_digest,
                    result["effect_id"], receipt["committed_at"], authorization["fence_scope"],
                    authorization["fence_owner"], authorization["fence_epoch"],
                ),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        if lose_ack:
            raise TimeoutError("committed queued SQLite destination effect; acknowledgement dropped")
        return result, receipt
