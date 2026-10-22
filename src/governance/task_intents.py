"""Bounded, immutable tenant task intent acceptance; no execution or admission.

An accepted record preserves authenticated submission provenance, not a reusable
principal. Workers, operation linkage and evidence-based settlement are separate
work. Result bytes are reserved capacity only; this module has no result writer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..protocols.durable_task_lifecycle import LifecycleCapacity
from ..protocols.task_lifecycle import TaskLifecycle, _identifier
from .authority import AuthorityDenied
from .operation_ledger import OperationConflict
from .store import PostgresStore, SqliteStore, sql_atomic
from .tenant_store import _install_postgres_guards, _install_sqlite_guards, _quote


class TaskIntentConflict(OperationConflict):
    """A retained task or operation identity cannot be reused or replaced."""


class TaskIntentCapacity(ValueError):
    """Persisted intent bounds are unavailable or admission is saturated."""


class TaskSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_scope: Literal["task.submit"]
    task_id: str = Field(min_length=1, max_length=128)
    context_id: str = Field(min_length=1, max_length=128)
    src: str = Field(min_length=1, max_length=32)
    dst: str = Field(min_length=1, max_length=32)
    wire: dict
    operation_id: str = Field(min_length=16, max_length=128)
    target_id: str = Field(min_length=1, max_length=128)


def parse_submission(body):
    """Apply the HTTP request contract to direct authenticated session calls."""
    if not isinstance(body, bytes) or len(body) > 1048576:
        raise ValueError("bounded signed JSON request required")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError("finite JSON required")

    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
        submission = TaskSubmission.model_validate(value)
        for name in ("src", "dst", "target_id", "operation_id"):
            _identifier(getattr(submission, name), name)
        # Validate provenance identifiers without mutating lifecycle state.
        TaskLifecycle(submission.task_id, submission.context_id, "agentbridge")
        return submission
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid task submission") from exc


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True)
class IntentLimits:
    max_intent_bytes: int = 65536
    max_result_bytes: int = 65536
    max_intents: int = 1024
    max_retained_bytes: int = 134217728

    def validated(self):
        for name, minimum, maximum in (
            ("max_intent_bytes", 256, 1048576),
            ("max_result_bytes", 1, 1048576),
            ("max_intents", 1, 1000000),
            ("max_retained_bytes", 256, 1073741824),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid bounded intent capacity: " + name)
        return self


class TaskIntentStore:
    """Private tenant SQL records sharing lifecycle/audit acceptance transactions.

    The lifecycle lock also serializes intent admission across connections.
    Immutable SQL rows prevent replacement/deletion through application writes.
    Administrators and uncoordinated database rollback remain outside this local
    persistence contract. Initialize once before admitting requests.
    """

    _TABLES = ("task_intents_v1", "task_intent_policy_v1", "task_intent_meta_v1")

    def __init__(self, store, tasks):
        if not isinstance(store, (SqliteStore, PostgresStore)) or not getattr(store, "tenant_id", None):
            raise ValueError("private bound tenant SQL store required")
        if tasks.store is not store:
            raise ValueError("intent and lifecycle must share one store")
        self.store, self.tasks = store, tasks
        self.postgres = isinstance(store, PostgresStore)
        self._bytes = "octet_length(record)" if self.postgres else "length(CAST(record AS BLOB))"
        with self._transaction():
            if self.postgres:
                rows = self._execute(
                    "SELECT c.relname AS name,c.relkind AS kind FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() AND c.relname IN (?,?,?)", self._TABLES
                ).fetchall()
                kind = "r"
            else:
                rows = self._execute(
                    "SELECT name,type AS kind FROM sqlite_master WHERE name IN (?,?,?)", self._TABLES
                ).fetchall()
                kind = "table"
            existing = {row["name"] for row in rows if row["kind"] == kind}
            if len(existing) != len(rows) or (existing and existing != set(self._TABLES)):
                raise TaskIntentCapacity("incomplete persisted intent schema; reviewed recovery required")
            self._execute(
                "CREATE TABLE IF NOT EXISTS task_intents_v1 ("
                "owner_id TEXT NOT NULL,task_id TEXT NOT NULL,agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
                "fingerprint TEXT NOT NULL,record TEXT NOT NULL,result_limit_bytes BIGINT NOT NULL "
                "CHECK(result_limit_bytes BETWEEN 1 AND 1048576),PRIMARY KEY(owner_id,task_id),"
                "UNIQUE(agent_id,operation_id))"
            )
            self._execute(
                "CREATE TABLE IF NOT EXISTS task_intent_policy_v1 (singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                "version INTEGER NOT NULL,max_intent_bytes BIGINT NOT NULL,max_result_bytes BIGINT NOT NULL,"
                "max_intents BIGINT NOT NULL,max_retained_bytes BIGINT NOT NULL)"
            )
            self._execute(
                "CREATE TABLE IF NOT EXISTS task_intent_meta_v1 "
                "(singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL)"
            )
            if not existing:
                limits = IntentLimits()
                self._execute("INSERT INTO task_intent_meta_v1 VALUES(1,1)")
                self._execute("INSERT INTO task_intent_policy_v1 VALUES(1,1,?,?,?,?)", tuple(asdict(limits).values()))
            self._policy()
            self._install_guards()
            if self.postgres:
                with store._db.cursor() as cur:
                    _install_postgres_guards(cur, store.schema, self._TABLES)
            else:
                _install_sqlite_guards(store._db, self._TABLES)

    @contextmanager
    def _transaction(self):
        with sql_atomic(self.store):
            if self.postgres:
                isolation = self._execute("SHOW transaction_isolation").fetchone()["transaction_isolation"]
                if isolation != "read committed":
                    raise TaskIntentCapacity("task intent transactions require PostgreSQL READ COMMITTED")
                self._execute("SELECT pg_advisory_xact_lock(?)", (911006,))
            yield

    def _execute(self, query, values=()):
        return self.store._db.execute(query.replace("?", "%s") if self.postgres else query, values)

    def _policy(self):
        row = self._execute(
            "SELECT p.* FROM task_intent_policy_v1 p JOIN task_intent_meta_v1 m "
            "ON m.singleton=p.singleton AND m.version=1 WHERE p.singleton=1"
        ).fetchone()
        try:
            if row is None or row["version"] != 1:
                raise ValueError("unsupported intent policy")
            return IntentLimits(**{name: row[name] for name in asdict(IntentLimits())}).validated()
        except (TypeError, ValueError) as exc:
            raise TaskIntentCapacity("missing or unsupported persisted intent policy") from exc

    def _usage(self):
        return self._execute(
            "SELECT count(*) AS used_intents,COALESCE(SUM(" + self._bytes + "+result_limit_bytes),0) "
            "AS used_retained_bytes FROM task_intents_v1"
        ).fetchone()

    def capacity(self):
        with self._transaction():
            return {**asdict(self._policy()), **dict(self._usage())}

    def set_capacity(self, limits, *, audit):
        if not isinstance(limits, IntentLimits):
            raise ValueError("validated intent capacity required")
        limits.validated()
        with self._transaction():
            self._policy()
            used = self._usage()
            if limits.max_intents < used["used_intents"] or limits.max_retained_bytes < used["used_retained_bytes"]:
                raise TaskIntentCapacity("capacity cannot discard retained intent history or result allowances")
            self._execute(
                "UPDATE task_intent_policy_v1 SET max_intent_bytes=?,max_result_bytes=?,"
                "max_intents=?,max_retained_bytes=? WHERE singleton=1", tuple(asdict(limits).values())
            )
            audit()

    def _accept(self, owner_id, submission, provenance, *, audit):
        """Trusted session only: acceptance writes no operation, budget or approval."""
        with self._transaction():
            limits = self._policy()
            if self._execute(
                "SELECT 1 FROM task_intents_v1 WHERE (owner_id=? AND task_id=?) OR (agent_id=? AND operation_id=?)",
                (owner_id, submission.task_id, provenance["authority"]["agent_id"], submission.operation_id),
            ).fetchone() or self._execute(
                "SELECT 1 FROM task_lifecycle_snapshots WHERE owner_id=? AND task_id=?",
                (owner_id, submission.task_id),
            ).fetchone() or self._execute(
                "SELECT 1 FROM agent_operations WHERE agent_id=? AND operation_id=?",
                (provenance["authority"]["agent_id"], submission.operation_id),
            ).fetchone():
                raise TaskIntentConflict("retained task or operation identity already exists; no replacement")
            now = self._execute(
                "SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now" if self.postgres
                else "SELECT (julianday('now')-2440587.5)*86400.0 AS now"
            ).fetchone()["now"]
            record = {
                "domain": "agentbridge.queued-task-intent.v1", "submission": submission.model_dump(),
                "provenance": provenance, "accepted_at": float(now), "phase": "queued",
                "execution_admitted": False,
            }
            raw = _json(record)
            fingerprint = hashlib.sha256(raw.encode()).hexdigest()
            size = len(raw.encode())
            usage = self._usage()
            if size > limits.max_intent_bytes or usage["used_intents"] >= limits.max_intents or \
                    usage["used_retained_bytes"] + size + limits.max_result_bytes > limits.max_retained_bytes:
                raise TaskIntentCapacity("retained intent capacity reached; reviewed capacity increase required")
            self._execute(
                "INSERT INTO task_intents_v1 VALUES(?,?,?,?,?,?,?)",
                (owner_id, submission.task_id, provenance["authority"]["agent_id"], submission.operation_id,
                 fingerprint, raw, limits.max_result_bytes),
            )
            try:
                self.tasks.create(owner_id, TaskLifecycle(submission.task_id, submission.context_id, "agentbridge"))
            except LifecycleCapacity as exc:
                # Submission capacity has one API contract even when the
                # lifecycle participant, rather than the intent policy, is full.
                raise TaskIntentCapacity("task lifecycle capacity unavailable for queued intent") from exc
            audit(fingerprint)
            return {**json.loads(raw), "intent_sha256": fingerprint, "result_limit_bytes": limits.max_result_bytes}

    def get(self, owner_id, task_id):
        _identifier(owner_id, "authenticated owner_id")
        _identifier(task_id, "task_id")
        with self._transaction():
            row = self._execute(
                "SELECT record,fingerprint,result_limit_bytes FROM task_intents_v1 WHERE owner_id=? AND task_id=?",
                (owner_id, task_id),
            ).fetchone()
            if row is None:
                raise AuthorityDenied("task intent unavailable for authenticated owner")
            return {**json.loads(row["record"]), "intent_sha256": row["fingerprint"],
                    "result_limit_bytes": row["result_limit_bytes"]}

    def _load_for_execution(self, owner_id, task_id, expected_intent_sha256):
        """Read accepted history, without acquiring an operation/lifecycle lock.

        This is integrity/ownership validation, never authority to execute. The
        caller must subsequently use the private enrolled-authority guard.
        """
        from .queued_intent_preparation import _StoredIntent
        from .tenant_kernel import binding_owner

        _identifier(owner_id, "authenticated owner_id")
        _identifier(task_id, "task_id")
        if not isinstance(expected_intent_sha256, str) or not re.fullmatch("[0-9a-f]{64}", expected_intent_sha256):
            raise AuthorityDenied("exact retained intent digest required")
        self.store.assert_scope()
        with self.store._lock:
            if self.postgres and self._execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
                raise AuthorityDenied("queued intent readback requires PostgreSQL READ COMMITTED")
            row = self._execute(
                "SELECT i.*,s.snapshot AS current_snapshot,e.snapshot AS initial_snapshot "
                "FROM task_intents_v1 i LEFT JOIN task_lifecycle_snapshots s "
                "ON s.owner_id=i.owner_id AND s.task_id=i.task_id LEFT JOIN task_lifecycle_events e "
                "ON e.owner_id=i.owner_id AND e.task_id=i.task_id AND e.sequence=0 "
                "WHERE i.owner_id=? AND i.task_id=?", (owner_id, task_id),
            ).fetchone()
        try:
            if row is None or row["fingerprint"] != expected_intent_sha256 or \
                    hashlib.sha256(row["record"].encode()).hexdigest() != expected_intent_sha256:
                raise ValueError("intent digest mismatch")
            record = json.loads(row["record"])
            provenance = record["provenance"]
            authority = provenance["authority"]
            body = provenance["request_body"].encode("utf-8")
            submission = parse_submission(body)
            deadline = provenance["authorization_expires_at"]
            accepted = record["accepted_at"]
            if record["domain"] != "agentbridge.queued-task-intent.v1" or record["phase"] != "queued" or \
                    record["execution_admitted"] is not False or provenance["authentication"] != "enrolled-tenant-request-v2":
                raise ValueError("unsupported retained intent")
            if type(deadline) not in (int, float) or not math.isfinite(deadline) or \
                    type(accepted) not in (int, float) or not math.isfinite(accepted) or not 0 < accepted < deadline:
                raise ValueError("invalid original authorization interval")
            if hashlib.sha256(body).hexdigest() != provenance["request_body_sha256"] or \
                    _json(submission.model_dump()) != _json(record["submission"]):
                raise ValueError("original body binding mismatch")
            if authority["tenant_id"] != self.store.tenant_id or authority["agent_id"] != row["agent_id"] or \
                    authority["kind"] not in ("machine", "delegated_human") or binding_owner(authority) != owner_id or \
                    submission.task_id != task_id or submission.operation_id != row["operation_id"]:
                raise ValueError("retained owner or action mismatch")
            if type(row["result_limit_bytes"]) is not int or not 1 <= row["result_limit_bytes"] <= 1048576:
                raise ValueError("invalid immutable result allowance")
            initial = self.tasks._decode(row["initial_snapshot"])
            current = self.tasks._decode(row["current_snapshot"])
            if initial != TaskLifecycle(task_id, submission.context_id, "agentbridge") or current != initial:
                raise ValueError("retained intent is not an initial native queued task")
            return _StoredIntent(owner_id, task_id, row["agent_id"], row["operation_id"],
                                 expected_intent_sha256, row["record"], row["result_limit_bytes"])
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, RecursionError) as exc:
            raise AuthorityDenied("retained queued intent integrity or ownership unavailable") from exc

    def _install_guards(self):
        # Database bounds count encoded payloads plus each immutable result
        # allowance, rather than trusting caller-maintained accounting columns.
        policy = (
            "p.version=1 AND m.version=1 AND p.max_intent_bytes BETWEEN 256 AND 1048576 "
            "AND p.max_result_bytes BETWEEN 1 AND 1048576 AND p.max_intents BETWEEN 1 AND 1000000 "
            "AND p.max_retained_bytes BETWEEN 256 AND 1073741824"
        )
        if not self.postgres:
            policy += " AND " + " AND ".join(
                "typeof(p." + name + ")='integer'" for name in asdict(IntentLimits())
            )
            self._execute(
                "CREATE TRIGGER IF NOT EXISTS task_intent_bounds_v1 BEFORE INSERT ON task_intents_v1 WHEN "
                "NOT EXISTS (SELECT 1 FROM task_intent_policy_v1 p JOIN task_intent_meta_v1 m "
                "ON p.singleton=m.singleton WHERE p.singleton=1 AND " + policy +
                " AND length(CAST(NEW.record AS BLOB))<=p.max_intent_bytes "
                "AND NEW.result_limit_bytes=p.max_result_bytes "
                "AND (SELECT count(*) FROM task_intents_v1)<p.max_intents "
                "AND (SELECT COALESCE(SUM(length(CAST(record AS BLOB))+result_limit_bytes),0) "
                "FROM task_intents_v1)+length(CAST(NEW.record AS BLOB))+NEW.result_limit_bytes<=p.max_retained_bytes) "
                "BEGIN SELECT RAISE(ABORT,'intent capacity reached or policy unavailable'); END"
            )
            for action in ("UPDATE", "DELETE"):
                self._execute(
                    "CREATE TRIGGER IF NOT EXISTS task_intent_immutable_" + action.lower() + "_v1 BEFORE " + action +
                    " ON task_intents_v1 BEGIN SELECT RAISE(ABORT,'task intent history is immutable'); END"
                )
            return
        namespace = _quote(self.store.schema) + "."
        bounds = namespace + "task_intent_bounds_v1"
        self._execute(
            "CREATE OR REPLACE FUNCTION " + bounds + "() RETURNS trigger LANGUAGE plpgsql "
            "SET search_path=pg_catalog AS $$ BEGIN "
            "IF current_setting('transaction_isolation')<>'read committed' THEN "
            "RAISE EXCEPTION 'task intent transactions require PostgreSQL READ COMMITTED'; END IF; "
            "PERFORM pg_advisory_xact_lock(911006); "
            "IF NOT EXISTS (SELECT 1 FROM " + namespace + "task_intent_policy_v1 p JOIN " + namespace +
            "task_intent_meta_v1 m ON p.singleton=m.singleton WHERE p.singleton=1 AND " + policy +
            " AND octet_length(NEW.record)<=p.max_intent_bytes AND NEW.result_limit_bytes=p.max_result_bytes "
            "AND (SELECT count(*) FROM " + namespace + "task_intents_v1)<p.max_intents "
            "AND (SELECT COALESCE(SUM(octet_length(record)+result_limit_bytes),0) FROM " + namespace +
            "task_intents_v1)+octet_length(NEW.record)+NEW.result_limit_bytes<=p.max_retained_bytes) THEN "
            "RAISE EXCEPTION 'intent capacity reached or policy unavailable'; END IF; RETURN NEW; END $$"
        )
        immutable = namespace + "task_intent_immutable_v1"
        self._execute(
            "CREATE OR REPLACE FUNCTION " + immutable + "() RETURNS trigger LANGUAGE plpgsql "
            "SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'task intent history is immutable'; END $$"
        )
        for name, actions, level, function in (
            ("task_intent_bounds_v1", "INSERT", "ROW", bounds),
            ("task_intent_immutable_v1", "UPDATE OR DELETE OR TRUNCATE", "STATEMENT", immutable),
        ):
            self._execute("DROP TRIGGER IF EXISTS " + name + " ON task_intents_v1")
            self._execute("CREATE TRIGGER " + name + " BEFORE " + actions + " ON task_intents_v1 FOR EACH " +
                          level + " EXECUTE FUNCTION " + function + "()")
