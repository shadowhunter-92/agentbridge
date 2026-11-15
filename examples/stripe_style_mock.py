"""Offline PaymentIntent-shaped reference example; never a Stripe client.

Permanent request bindings and no-resend are this mock's conservative contract,
not Stripe API guarantees. All effects use the existing fenced SQLite target.
No credentials, sockets, SDK calls, money movement, or production path exist.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from dataclasses import asdict, dataclass

from src.governance.fenced_sqlite_destination import FencedSqliteTarget
from src.governance.sandbox_readback import ObservationUnavailable, SandboxReadOnlyObserver
from src.governance.trust_sdk import verify_action_evidence


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None


def _not_production():
    import os

    if os.environ.get("AGENTBRIDGE_ENV", "").lower() in {"production", "prod"}:
        raise RuntimeError("offline Stripe-style example refuses production mode")


class MockRequestConflict(RuntimeError):
    """An existing key/operation cannot authorize another send."""


class WebhookRejected(ValueError):
    """No inbox entry was accepted."""


class MockCapacityDenied(ValueError):
    """Invalid or exhausted retained storage; never permission to resend."""


@dataclass(frozen=True)
class MockStorageLimits:
    max_records: int = 10_000
    max_bytes: int = 16 * 1024 * 1024
    max_entry_bytes: int = 64 * 1024

    def __post_init__(self):
        for name, ceiling in (("max_records", 100_000), ("max_bytes", 512 * 1024 * 1024),
                              ("max_entry_bytes", 1024 * 1024)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= ceiling:
                raise MockCapacityDenied("positive bounded mock storage limits required")
        if self.max_entry_bytes > self.max_bytes:
            raise MockCapacityDenied("mock entry exceeds aggregate byte limit")


_STORAGE_POLICY = "mock_stripe_capacity_v1"
_PAYLOAD_DDL = {
    "mock_stripe_attempts": "CREATE TABLE IF NOT EXISTS mock_stripe_attempts (idempotency_key TEXT PRIMARY KEY, agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, request_json BLOB NOT NULL, fingerprint TEXT NOT NULL, UNIQUE(agent_id,operation_id))",
    "sandbox_effects": "CREATE TABLE IF NOT EXISTS sandbox_effects (agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, fingerprint TEXT NOT NULL, outcome TEXT NOT NULL, external_reference TEXT NOT NULL, receipt_json TEXT NOT NULL, PRIMARY KEY(agent_id,operation_id))",
    "mock_stripe_webhooks": "CREATE TABLE IF NOT EXISTS mock_stripe_webhooks (event_id TEXT PRIMARY KEY, event_sha256 TEXT NOT NULL, event_json BLOB NOT NULL)",
}
_PAYLOAD_FIELDS = {
    "mock_stripe_attempts": ("idempotency_key", "agent_id", "operation_id", "request_json", "fingerprint"),
    "sandbox_effects": ("agent_id", "operation_id", "fingerprint", "outcome", "external_reference", "receipt_json"),
    "mock_stripe_webhooks": ("event_id", "event_sha256", "event_json"),
}
_POLICY_DDL = ("CREATE TABLE mock_stripe_capacity_v1 ("
               "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL CHECK(version=1),"
               "max_records INTEGER NOT NULL CHECK(typeof(max_records)='integer' AND max_records BETWEEN 1 AND 100000),"
               "max_bytes INTEGER NOT NULL CHECK(typeof(max_bytes)='integer' AND max_bytes BETWEEN 1 AND 536870912),"
               "max_entry_bytes INTEGER NOT NULL CHECK(typeof(max_entry_bytes)='integer' AND max_entry_bytes BETWEEN 1 AND 1048576 AND max_entry_bytes<=max_bytes))")
_RESERVED_STORAGE = (_STORAGE_POLICY, *_PAYLOAD_FIELDS, "mock_stripe_binding", "ab_destination_fences")


def _sql_normalized(value):
    return "".join(value.replace("IF NOT EXISTS ", "").split()).rstrip(";").casefold()


def _storage_namespace(db):
    placeholders = ",".join("?" for _ in _RESERVED_STORAGE)
    if db.execute("SELECT 1 FROM sqlite_temp_master WHERE name COLLATE NOCASE IN (" + placeholders + ") "
                  "OR tbl_name COLLATE NOCASE IN (" + placeholders + ") LIMIT 1",
                  _RESERVED_STORAGE * 2).fetchone():
        raise MockCapacityDenied("mock storage name shadowed by TEMP object")
    if any(row[1] not in {"main", "temp"} for row in db.execute("PRAGMA database_list")):
        raise MockCapacityDenied("attached namespaces are outside the mock storage contract")
    if db.execute("PRAGMA main.encoding").fetchone()[0] != "UTF-8":
        raise MockCapacityDenied("mock storage requires UTF-8 SQLite encoding")
    if db.execute("SELECT 1 FROM main.sqlite_master WHERE name LIKE 'ab_queued_%' LIMIT 1").fetchone():
        raise MockCapacityDenied("queued-only destination is outside the mock storage contract")


def _row_bytes(table, prefix=""):
    return "+".join("length(CAST(" + prefix + field + " AS BLOB))" for field in _PAYLOAD_FIELDS[table])


def _invalid_types(table, prefix=""):
    return " OR ".join("typeof(" + prefix + field + ")<>'" + (
        "blob" if field in {"request_json", "event_json"} else "text") + "'"
                        for field in _PAYLOAD_FIELDS[table])


def _aggregate_sql():
    return " UNION ALL ".join("SELECT " + _row_bytes(table) + " AS n FROM " + table
                              for table in _PAYLOAD_FIELDS)


def _storage_triggers():
    aggregate = _aggregate_sql()
    duplicate = {
        "mock_stripe_attempts": "idempotency_key=NEW.idempotency_key OR (agent_id=NEW.agent_id AND operation_id=NEW.operation_id)",
        "sandbox_effects": "agent_id=NEW.agent_id AND operation_id=NEW.operation_id",
        "mock_stripe_webhooks": "event_id=NEW.event_id",
    }
    statements = {}
    for table in _PAYLOAD_FIELDS:
        name = "mock_storage_" + table + "_insert_v1"
        types = _invalid_types(table, "NEW.")
        statements[name] = ("CREATE TRIGGER " + name + " AFTER INSERT ON " + table + " BEGIN "
                            "SELECT CASE WHEN (SELECT count(*) FROM " + _STORAGE_POLICY + ")<>1 OR " + types +
                            " THEN RAISE(ABORT,'invalid mock retained policy or value type') END; "
                            "SELECT CASE WHEN (SELECT count(*) FROM (" + aggregate + "))>"
                            "(SELECT max_records FROM " + _STORAGE_POLICY + ") OR "
                            "(SELECT coalesce(sum(n),0) FROM (" + aggregate + "))>"
                            "(SELECT max_bytes FROM " + _STORAGE_POLICY + ") OR " + _row_bytes(table, "NEW.") +
                            ">(SELECT max_entry_bytes FROM " + _STORAGE_POLICY + ") "
                            "THEN RAISE(ABORT,'mock retained capacity reached') END; END")
        name = "mock_storage_" + table + "_duplicate_v1"
        statements[name] = ("CREATE TRIGGER " + name + " BEFORE INSERT ON " + table +
                            " WHEN EXISTS(SELECT 1 FROM " + table + " WHERE " + duplicate[table] + ") "
                            "BEGIN SELECT RAISE(ABORT,'mock retained record already exists'); END")
        for operation in ("UPDATE", "DELETE"):
            name = "mock_storage_" + table + "_" + operation.lower() + "_v1"
            statements[name] = ("CREATE TRIGGER " + name + " BEFORE " + operation + " ON " + table +
                                " BEGIN SELECT RAISE(ABORT,'immutable mock retained record'); END")
    name = "mock_storage_policy_duplicate_v1"
    statements[name] = ("CREATE TRIGGER " + name + " BEFORE INSERT ON " + _STORAGE_POLICY +
                        " WHEN EXISTS(SELECT 1 FROM " + _STORAGE_POLICY + ") "
                        "BEGIN SELECT RAISE(ABORT,'immutable mock storage policy'); END")
    for operation in ("UPDATE", "DELETE"):
        name = "mock_storage_policy_" + operation.lower() + "_v1"
        statements[name] = ("CREATE TRIGGER " + name + " BEFORE " + operation + " ON " + _STORAGE_POLICY +
                            " BEGIN SELECT RAISE(ABORT,'immutable mock storage policy'); END")
    return statements


def _qualify_storage(db, limits=None):
    _storage_namespace(db)
    for name, expected in {**_PAYLOAD_DDL, _STORAGE_POLICY: _POLICY_DDL, **_storage_triggers()}.items():
        row = db.execute("SELECT name,sql FROM main.sqlite_master WHERE name COLLATE NOCASE=?", (name,)).fetchone()
        if (not row or row[0] != name or not isinstance(row[1], str)
                or _sql_normalized(row[1]) != _sql_normalized(expected)):
            raise MockCapacityDenied("missing or modified mock storage schema/guard")
    rows = db.execute("SELECT singleton,version,max_records,max_bytes,max_entry_bytes FROM main." + _STORAGE_POLICY).fetchall()
    if len(rows) != 1 or tuple(rows[0][:2]) != (1, 1):
        raise MockCapacityDenied("missing or unsupported mock storage policy")
    policy = MockStorageLimits(*rows[0][2:])
    if limits is not None and (not isinstance(limits, MockStorageLimits) or limits != policy):
        raise MockCapacityDenied("persisted mock storage policy cannot be changed on reopen")
    for table in _PAYLOAD_FIELDS:
        if db.execute("SELECT 1 FROM main." + table + " WHERE " + _invalid_types(table) + " LIMIT 1").fetchone():
            raise MockCapacityDenied("unsupported historical mock storage value type")
    usage = db.execute("SELECT count(*),coalesce(sum(n),0),coalesce(max(n),0) FROM (" + _aggregate_sql() + ")").fetchone()
    if (usage[0] > policy.max_records or usage[1] > policy.max_bytes or usage[2] > policy.max_entry_bytes):
        raise MockCapacityDenied("existing mock history exceeds retained capacity")
    return {**asdict(policy), "used_records": usage[0], "used_bytes": usage[1]}


def _open_storage(path, limits):
    if not isinstance(path, str) or not path or path == ":memory:":
        raise MockCapacityDenied("durable local mock storage path required")
    if limits is not None and not isinstance(limits, MockStorageLimits):
        raise MockCapacityDenied("typed mock storage limits required")
    db = sqlite3.connect(path, isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        _storage_namespace(db)
        installed = db.execute("SELECT 1 FROM main.sqlite_master WHERE name COLLATE NOCASE=?", (_STORAGE_POLICY,)).fetchone()
        if not installed:
            if db.execute("SELECT 1 FROM main.sqlite_master WHERE name LIKE 'mock_storage_%' LIMIT 1").fetchone():
                raise MockCapacityDenied("partial mock capacity installation cannot be reset")
            for statement in _PAYLOAD_DDL.values():
                db.execute(statement)
            db.execute(_POLICY_DDL)
            policy = limits or MockStorageLimits()
            db.execute("INSERT INTO main." + _STORAGE_POLICY + " VALUES(1,1,?,?,?)",
                       tuple(asdict(policy).values()))
            for statement in _storage_triggers().values():
                db.execute(statement)
        _qualify_storage(db, limits)
        db.execute("COMMIT")
        return db
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        db.close()
        raise


def _storage_snapshot(db):
    db.execute("BEGIN")
    try:
        state = _qualify_storage(db)
        db.execute("COMMIT")
        return state
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


@dataclass(frozen=True)
class PaymentIntentRequest:
    target_id: str
    agent_id: str
    operation_id: str
    amount: int
    currency: str = "usd"

    def __post_init__(self):
        if not all(_identifier(x) for x in (self.target_id, self.agent_id, self.operation_id)):
            raise ValueError("bounded target, agent and operation identifiers required")
        if type(self.amount) is not int or not 1 <= self.amount <= 100_000_000:
            raise ValueError("bounded positive integer minor-unit amount required")
        if self.currency != "usd":
            raise ValueError("offline example supports usd only")

    @property
    def canonical(self):
        return _json({"domain": "agentbridge.stripe-style-mock.v1", **self.__dict__})

    @property
    def fingerprint(self):
        return hashlib.sha256(self.canonical).hexdigest()

    @property
    def idempotency_key(self):
        # Stable operation identity, not a hash of mutable purchase arguments.
        identity = [self.target_id, self.agent_id, self.operation_id]
        return "mock_" + hashlib.sha256(_json(identity)).hexdigest()

    def succeeded_intent(self):
        return {"id": "pi_mock_" + self.idempotency_key[5:29], "object": "payment_intent",
                "amount": self.amount, "amount_received": self.amount, "currency": self.currency,
                "status": "succeeded", "livemode": False,
                "metadata": {"target_id": self.target_id, "agent_id": self.agent_id,
                             "operation_id": self.operation_id, "fingerprint": self.fingerprint}}


class StripeStyleMock:
    """Operator-bound, one-shot local create-and-confirm *simulation*.

    A durable immutable attempt binding precedes the existing target effect.
    A crash between those commits can leave no effect and UNKNOWN forever;
    this class never interprets absence as failure or automatically resends.
    """
    def __init__(self, path, *, target_id, sign, limits=None):
        _not_production()
        if not _identifier(target_id):
            raise ValueError("bounded operator target required")
        self.target_id = target_id
        self.scope = "mock-stripe:" + target_id
        if not callable(sign):
            raise ValueError("destination signer required")
        prepared = _open_storage(path, limits)
        prepared.close()
        self.target = FencedSqliteTarget(path, sign=sign)
        db = self.target.db
        try:
            db.execute("BEGIN IMMEDIATE")
            _qualify_storage(db, limits)
            db.execute("CREATE TABLE IF NOT EXISTS mock_stripe_binding (singleton INTEGER PRIMARY KEY CHECK(singleton=1), target_id TEXT NOT NULL)")
            row = db.execute("SELECT target_id FROM mock_stripe_binding WHERE singleton=1").fetchone()
            if row and row["target_id"] != target_id:
                raise ValueError("mock database is bound to another target")
            db.execute("INSERT OR IGNORE INTO mock_stripe_binding VALUES(1,?)", (target_id,))
            db.execute("CREATE TABLE IF NOT EXISTS mock_stripe_attempts (idempotency_key TEXT PRIMARY KEY, agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, request_json BLOB NOT NULL, fingerprint TEXT NOT NULL, UNIQUE(agent_id,operation_id))")
            for table in ("mock_stripe_binding", "mock_stripe_attempts"):
                for verb in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'immutable mock record'); END")
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            self.target.close()
            raise

    def close(self):
        self.target.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def acquire(self, *, owner, ttl_seconds=15):
        _not_production()
        _storage_snapshot(self.target.db)
        return self.target.acquire(scope=self.scope, owner=owner, ttl_seconds=ttl_seconds)

    def capacity(self):
        return _storage_snapshot(self.target.db)

    def confirm(self, request, *, owner, epoch, lose_ack=False):
        _not_production()
        if not isinstance(request, PaymentIntentRequest) or request.target_id != self.target_id:
            raise ValueError("request does not bind the operator target")
        if not _identifier(owner) or type(epoch) is not int or epoch < 1 or type(lose_ack) is not bool:
            raise ValueError("valid owner, epoch and fault flag required")
        db = self.target.db
        db.execute("BEGIN IMMEDIATE")
        try:
            _qualify_storage(db)
            row = db.execute("SELECT request_json,fingerprint FROM mock_stripe_attempts WHERE idempotency_key=? OR (agent_id=? AND operation_id=?)",
                             (request.idempotency_key, request.agent_id, request.operation_id)).fetchone()
            if row:
                if bytes(row["request_json"]) != request.canonical or row["fingerprint"] != request.fingerprint:
                    raise MockRequestConflict("same operation/key has different arguments")
                raise MockRequestConflict("existing attempt; readback only, no resend")
            db.execute("INSERT INTO mock_stripe_attempts VALUES(?,?,?,?,?)",
                       (request.idempotency_key, request.agent_id, request.operation_id,
                        request.canonical, request.fingerprint))
            db.execute("COMMIT")
        except BaseException as exc:
            if db.in_transaction:
                db.execute("ROLLBACK")
            if isinstance(exc, sqlite3.IntegrityError) and "mock retained" in str(exc):
                raise MockCapacityDenied("mock retained capacity refused; preserve existing evidence") from exc
            raise
        try:
            receipt = self.target.commit(scope=self.scope, owner=owner, epoch=epoch,
                                         agent_id=request.agent_id, operation_id=request.operation_id,
                                         fingerprint=request.fingerprint, lose_ack=lose_ack)
        except sqlite3.IntegrityError as exc:
            if "mock retained" in str(exc):
                raise MockCapacityDenied("effect capacity refused after durable attempt; outcome unknown, no resend") from exc
            raise
        return request.succeeded_intent(), receipt


class StripeStyleReadback(SandboxReadOnlyObserver):
    """A separate read-only handle using the existing receipt/observer contract.

    This example's keys and file still share one local test trust domain.
    """
    def observe_payment(self, request):
        _not_production()
        if not isinstance(request, PaymentIntentRequest):
            raise ObservationUnavailable("exact expected mock request required")
        self._db.execute("BEGIN")
        try:
            _storage_namespace(self._db)
            binding = self._db.execute("SELECT target_id FROM mock_stripe_binding WHERE singleton=1").fetchone()
            row = self._db.execute("SELECT request_json,fingerprint FROM mock_stripe_attempts WHERE idempotency_key=? AND agent_id=? AND operation_id=?",
                                   (request.idempotency_key, request.agent_id, request.operation_id)).fetchone()
            if (not binding or binding["target_id"] != request.target_id or not row
                    or bytes(row["request_json"]) != request.canonical or row["fingerprint"] != request.fingerprint):
                raise ObservationUnavailable("mock request binding absent or mismatched; outcome unknown")
            receipt, proof = self.observe(agent_id=request.agent_id, operation_id=request.operation_id,
                                          fingerprint=request.fingerprint)
            self._db.execute("COMMIT")
            return request.succeeded_intent(), receipt, proof
        except BaseException as exc:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(exc, (sqlite3.Error, TypeError, ValueError)):
                raise ObservationUnavailable("mock state unavailable or malformed; outcome unknown") from exc
            raise


def verify_payment_evidence(request, intent, receipt, proof, *, destination_key_hex, readback_key_hex):
    """Offline evidence verification only; never settlement or fresh dispatch."""
    _not_production()
    if not isinstance(request, PaymentIntentRequest) or _json(intent) != _json(request.succeeded_intent()):
        raise ValueError("PaymentIntent-shaped result disagrees with expected request")
    return verify_action_evidence(
        destination_receipt=receipt, readback_attestation=proof, agent_id=request.agent_id,
        operation_id=request.operation_id, fingerprint=request.fingerprint, outcome="succeeded",
        external_reference="sqlite-fenced-effect:" + request.operation_id,
        destination_key_hex=destination_key_hex, readback_key_hex=readback_key_hex)


def sign_webhook(raw_body, *, secret, timestamp):
    """Synthetic fixture signer; the caller supplies a generated test secret."""
    if type(raw_body) is not bytes or not 0 < len(raw_body) <= 65_536:
        raise WebhookRejected("bounded raw bytes required")
    if type(secret) is not bytes or not 32 <= len(secret) <= 256:
        raise WebhookRejected("bounded synthetic signing secret required")
    if type(timestamp) is not int or not 0 <= timestamp <= 9_999_999_999:
        raise WebhookRejected("bounded integer timestamp required")
    digest = hmac.new(secret, str(timestamp).encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WebhookRejected("duplicate JSON member")
        result[key] = value
    return result


class WebhookInbox:
    """Persistent authenticated notification dedupe; no fulfillment or settlement.

    Freshly signed duplicates are normal. Out-of-order distinct events are stored
    without moving a PaymentIntent backwards or treating the event as readback.
    """
    def __init__(self, path, *, limits=None):
        _not_production()
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("durable local inbox path required")
        self.db = _open_storage(path, limits)

    def capacity(self):
        return _storage_snapshot(self.db)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def accept(self, raw_body, signature_header, *, secret, now, tolerance_seconds=300):
        _not_production()
        if (type(now) is not int or not 0 <= now <= 9_999_999_999
                or type(tolerance_seconds) is not int or not 1 <= tolerance_seconds <= 300
                or not isinstance(signature_header, str) or not 0 < len(signature_header) <= 4096):
            raise WebhookRejected("bounded clock, enabled tolerance and signature header required")
        fields = [part.strip().split("=", 1) for part in signature_header.split(",")]
        timestamps = [part[1] for part in fields if len(part) == 2 and part[0] == "t"]
        signatures = [part[1] for part in fields if len(part) == 2 and part[0] == "v1"]
        if len(timestamps) != 1 or re.fullmatch(r"[0-9]{1,10}", timestamps[0]) is None:
            raise WebhookRejected("one timestamp required")
        timestamp = int(timestamps[0])
        if timestamps[0] != str(timestamp):
            raise WebhookRejected("canonical timestamp required")
        expected = sign_webhook(raw_body, secret=secret, timestamp=timestamp).split("v1=", 1)[1]
        if abs(now - timestamp) > tolerance_seconds or not any(
                re.fullmatch(r"[0-9a-f]{64}", value) is not None and hmac.compare_digest(value, expected)
                for value in signatures):
            raise WebhookRejected("invalid signature or timestamp outside tolerance")
        try:
            event = json.loads(raw_body, object_pairs_hook=_unique_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(WebhookRejected("nonfinite JSON")))
            valid_types = {"payment_intent.succeeded", "payment_intent.processing", "payment_intent.payment_failed"}
            if (not isinstance(event, dict) or not _identifier(event.get("id"))
                    or event.get("object") != "event" or event.get("livemode") is not False
                    or event.get("type") not in valid_types
                    or not isinstance(event.get("data"), dict)
                    or not isinstance(event["data"].get("object"), dict)
                    or event["data"]["object"].get("object") != "payment_intent"
                    or not _identifier(event["data"]["object"].get("id"))
                    or event["data"]["object"].get("livemode") is not False):
                raise WebhookRejected("bounded synthetic PaymentIntent event required")
            canonical = _json(event)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
            raise WebhookRejected("malformed synthetic event") from exc
        digest = hashlib.sha256(canonical).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            _qualify_storage(self.db)
            row = self.db.execute("SELECT event_sha256 FROM mock_stripe_webhooks WHERE event_id=?", (event["id"],)).fetchone()
            if row and row[0] != digest:
                raise WebhookRejected("existing event ID has different content")
            if not row:
                self.db.execute("INSERT INTO mock_stripe_webhooks VALUES(?,?,?)", (event["id"], digest, canonical))
            self.db.execute("COMMIT")
        except BaseException as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            if isinstance(exc, sqlite3.IntegrityError) and "mock retained" in str(exc):
                raise MockCapacityDenied("mock inbox capacity refused; no notification or effect added") from exc
            raise
        return {"event_id": event["id"], "duplicate": bool(row), "effect_dispatched": False}
