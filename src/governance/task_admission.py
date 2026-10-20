"""Bounded immutable first-admission links; no dispatcher or result writer."""

from __future__ import annotations

import hashlib
import json
import re
import time

from ..protocols.task_lifecycle import TaskState, _identifier
from .authority import AuthorityDenied
from .store import PostgresStore, SqliteStore, sql_atomic
from .tenant_store import _install_postgres_guards, _install_sqlite_guards, _quote


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _action_scope(*, agent_id, src, dst, wire, cost, target_id, operation_id, authority):
    # Preserve the synchronous gateway's established fingerprint material.
    return hashlib.sha256(_json({
        "agent_id": agent_id, "src": src, "dst": dst, "wire": wire, "cost": cost,
        "target_id": target_id, "operation_id": operation_id, "authority": authority,
    }).encode()).hexdigest()


def _queued_scope(prepared):
    plan = prepared.plan
    principal = prepared._authority.principal
    original = _action_scope(
        agent_id=principal.agent_id, src=plan["src"], dst=plan["dst"], wire=plan["wire"],
        cost=plan["cost"], target_id=plan["target_id"], operation_id=plan["operation_id"],
        authority=principal.binding(),
    )
    return hashlib.sha256(_json({
        "domain": "agentbridge.queued-action.v1", "owner_id": plan["owner_id"],
        "task_id": plan["task_id"], "intent_sha256": plan["intent_sha256"],
        "original_action_sha256": original,
    }).encode()).hexdigest(), original


def _bound_gateway_runtime(gateway, prepared):
    from .queued_intent_preparation import _prepared_runtime
    from .tenant_kernel import TenantKernel

    kernel = getattr(gateway, "_queued_kernel", None)
    if not isinstance(kernel, TenantKernel):
        raise AuthorityDenied("operator-bound queued gateway required")
    runtime = _prepared_runtime(kernel, prepared)
    if runtime.gateway is not gateway or gateway.authority is not kernel.directory or \
            gateway.identities.store is not runtime.store or gateway.tenant_id != prepared.tenant_id:
        raise AuthorityDenied("queued preparation does not own this exact gateway runtime")
    return kernel, runtime


def _gateway_preparation(gateway, prepared):
    from .queued_intent_preparation import _assert_prepared

    kernel, runtime = _bound_gateway_runtime(gateway, prepared)
    _assert_prepared(kernel, prepared)
    return kernel, runtime


def _link(gateway, prepared, request_scope, token, decision):
    from .queued_intent_preparation import _assert_admission_lifetime, _assert_prepared

    kernel, runtime = _bound_gateway_runtime(gateway, prepared)
    plan = prepared.plan
    with runtime.tasks._transaction():
        # Only now acquire lifecycle911006: operation/quota/budget/approval
        # locks are already held by the common gateway admission transaction.
        _assert_prepared(kernel, prepared)
        task = runtime.tasks.transition(plan["owner_id"], plan["task_id"], TaskState.WORKING, expected_sequence=0)
        _, original = _queued_scope(prepared)
        metadata = {
            "domain": "agentbridge.task-admission.v1", "phase": "admitted", "execution_admitted": True,
            "tenant_id": prepared.tenant_id, "owner_id": plan["owner_id"], "task_id": plan["task_id"],
            "context_id": plan["context_id"], "agent_id": prepared._authority.principal.agent_id,
            "operation_id": plan["operation_id"], "intent_sha256": plan["intent_sha256"],
            "action_sha256": request_scope, "original_action_sha256": original,
            "reservation_token": token, "event_sequence": task.sequence, "task_state": task.state.value,
            "operation_state_at_admission": "unknown", "target_id": plan["target_id"],
            "target_configuration_sha256": plan["target_configuration_sha256"], "reserved_cost": plan["cost"],
            "approval_required": decision.approval_required, "result_limit_bytes": plan["result_limit_bytes"],
            "original_authorization_expires_at": plan["original_authorization_expires_at"], "admitted_at": time.time(),
        }
        receipt = runtime.task_admissions._insert(metadata, runtime.tasks._encode(task))
        runtime.audit.record(
            actor="principal:v1:" + _json(prepared._authority.principal.binding()), action="task.admit",
            source_protocol=plan["src"], target_protocol=plan["dst"], capability=plan["capability"],
            decision="allow", cost=0.0,
            reason="admitted queued action sha256:" + request_scope + "; link sha256:" + receipt["link_sha256"],
        )
        # Status is now WORKING. Do not broaden initial-only preparation or
        # reload it as if it were still SUBMITTED; check the sealed lifetime.
        _assert_admission_lifetime(kernel, prepared)
        return receipt


class TaskAdmissionStore:
    """One link per retained intent; constant SQL byte limits and no deletion."""

    TABLE = "task_operation_links_v1"
    META = "task_operation_links_meta_v1"
    COLUMNS = tuple((name, "BIGINT" if name == "event_sequence" else "TEXT") for name in (
        "owner_id", "task_id", "agent_id", "operation_id", "intent_sha256", "action_sha256",
        "reservation_token", "event_sequence", "snapshot", "record", "record_sha256",
    ))
    META_COLUMNS = (("singleton", "INTEGER"), ("version", "INTEGER"), ("schema_sha256", "TEXT"))
    SCHEMA_SHA256 = hashlib.sha256(_json({
        "version": 1, "columns": COLUMNS, "metadata_columns": META_COLUMNS,
        "receipt_bytes": 8192, "snapshot_bytes": 4096, "identifier_characters": 128, "identifier_bytes": 512,
        "primary_key": ["owner_id", "task_id"], "unique_operation": ["agent_id", "operation_id"],
    }).encode()).hexdigest()

    def __init__(self, store):
        if not isinstance(store, (SqliteStore, PostgresStore)) or not getattr(store, "tenant_id", None):
            raise ValueError("operator-bound tenant SQL store required")
        self.store, self.postgres = store, isinstance(store, PostgresStore)
        with sql_atomic(store):
            self._mode()
            if self.postgres:
                self._execute("SELECT pg_advisory_xact_lock(?)", (911004,))
                rows = self._execute(
                    "SELECT c.relname AS name,c.relkind AS kind FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname IN (?,?)",
                    (self.TABLE, self.META),
                ).fetchall()
                kind = "r"
            else:
                rows = self._execute("SELECT name,type AS kind FROM sqlite_master WHERE name IN (?,?)",
                                     (self.TABLE, self.META)).fetchall()
                kind = "table"
            existing = {row["name"] for row in rows if row["kind"] == kind}
            if len(existing) != len(rows) or (existing and existing != {self.TABLE, self.META}):
                raise AuthorityDenied("partial or unsupported task admission schema")
            if not existing:
                self._execute(
                "CREATE TABLE IF NOT EXISTS task_operation_links_v1 ("
                "owner_id TEXT NOT NULL,task_id TEXT NOT NULL,agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
                "intent_sha256 TEXT NOT NULL,action_sha256 TEXT NOT NULL,reservation_token TEXT NOT NULL,"
                "event_sequence BIGINT NOT NULL CHECK(event_sequence=1),snapshot TEXT NOT NULL,"
                "record TEXT NOT NULL,record_sha256 TEXT NOT NULL,PRIMARY KEY(owner_id,task_id),"
                "UNIQUE(agent_id,operation_id))"
                )
                self._execute(
                    "CREATE TABLE task_operation_links_meta_v1 (singleton INTEGER NOT NULL PRIMARY KEY "
                    "CHECK(singleton=1),version INTEGER NOT NULL,schema_sha256 TEXT NOT NULL)"
                )
                self._execute("INSERT INTO task_operation_links_meta_v1 VALUES(1,1,?)", (self.SCHEMA_SHA256,))
            self._qualify()
            self._guards()
            if self.postgres:
                with store._db.cursor() as cur:
                    _install_postgres_guards(cur, store.schema, (self.TABLE, self.META))
            else:
                _install_sqlite_guards(store._db, (self.TABLE, self.META))

    def _qualify(self):
        for table, expected in ((self.TABLE, self.COLUMNS), (self.META, self.META_COLUMNS)):
            if self.postgres:
                rows = self._execute(
                    "SELECT column_name AS name,data_type AS type,is_nullable FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position", (table,),
                ).fetchall()
                columns = [(row["name"], row["type"].upper()) for row in rows if row["is_nullable"] == "NO"]
                keys = self._execute(
                    "SELECT i.indisprimary AS primary_key,i.indisvalid AND i.indisready AND i.indpred IS NULL "
                    "AND i.indexprs IS NULL AND i.indnkeyatts=i.indnatts AS supported,"
                    "ARRAY(SELECT a.attname::text FROM unnest(i.indkey) WITH ORDINALITY k(attnum,pos) "
                    "LEFT JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.pos) AS cols "
                    "FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname=current_schema() AND t.relname=? AND i.indisunique",
                    (table,),
                ).fetchall()
                if any(not row["supported"] for row in keys):
                    raise AuthorityDenied("unsupported task admission schema shape")
                unique = {tuple(row["cols"]) for row in keys}
                primary = {tuple(row["cols"]) for row in keys if row["primary_key"]}
                unique_count = len(keys)
            else:
                rows = self._execute("PRAGMA table_info(" + _quote(table) + ")").fetchall()
                columns = [(row["name"], row["type"].upper()) for row in rows if row["notnull"]]
                primary = {tuple(row["name"] for row in sorted(rows, key=lambda item: item["pk"]) if row["pk"])}
                # INTEGER PRIMARY KEY is an implicit rowid key in SQLite;
                # unlike a composite primary key it has no index_list entry.
                unique = set(primary)
                unique_count = 0
                indexed_primary = False
                for index in self._execute("PRAGMA index_list(" + _quote(table) + ")").fetchall():
                    if index["unique"]:
                        names = tuple(row["name"] for row in self._execute(
                            "PRAGMA index_info(" + _quote(index["name"]) + ")"
                        ).fetchall())
                        if index["partial"] or None in names:
                            raise AuthorityDenied("unsupported task admission schema shape")
                        unique.add(names)
                        unique_count += 1
                        indexed_primary |= index["origin"] == "pk"
                if not indexed_primary:
                    unique_count += len(primary)
            required_primary = ("owner_id", "task_id") if table == self.TABLE else ("singleton",)
            required_unique = {required_primary}
            if table == self.TABLE:
                required_unique.add(("agent_id", "operation_id"))
            if len(rows) != len(expected) or columns != list(expected) or primary != {required_primary} or \
                    unique != required_unique or unique_count != len(required_unique):
                raise AuthorityDenied("unsupported task admission schema shape")
        rows = self._execute("SELECT * FROM task_operation_links_meta_v1").fetchall()
        if len(rows) != 1 or rows[0]["singleton"] != 1 or rows[0]["version"] != 1 or \
                rows[0]["schema_sha256"] != self.SCHEMA_SHA256:
            raise AuthorityDenied("unsupported task admission schema version or digest")

    def _execute(self, query, values=()):
        return self.store._db.execute(query.replace("?", "%s") if self.postgres else query, values)

    def _mode(self):
        if self.postgres and self._execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
            raise AuthorityDenied("queued admission requires PostgreSQL READ COMMITTED")

    def _insert(self, metadata, snapshot):
        self.store.assert_scope()
        self._mode()
        if self.postgres:
            from psycopg.pq import TransactionStatus

            active = self.store._db.info.transaction_status == TransactionStatus.INTRANS
        else:
            active = self.store._db.in_transaction
        if not active:
            raise RuntimeError("task linkage requires the owned admission transaction")
        raw = _json(metadata)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        self._execute(
            "INSERT INTO task_operation_links_v1 VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (metadata["owner_id"], metadata["task_id"], metadata["agent_id"], metadata["operation_id"],
             metadata["intent_sha256"], metadata["action_sha256"], metadata["reservation_token"],
             metadata["event_sequence"], snapshot, raw, digest),
        )
        return {**metadata, "link_sha256": digest}

    def get(self, owner_id, task_id, expected_intent_sha256):
        _identifier(owner_id, "owner_id")
        _identifier(task_id, "task_id")
        if not isinstance(expected_intent_sha256, str) or not re.fullmatch("[0-9a-f]{64}", expected_intent_sha256):
            raise AuthorityDenied("exact retained intent digest required")
        self.store.assert_scope()
        with self.store._lock:
            self._mode()
            row = self._execute(
                "SELECT * FROM task_operation_links_v1 WHERE owner_id=? AND task_id=? AND intent_sha256=?",
                (owner_id, task_id, expected_intent_sha256),
            ).fetchone()
        if row is None or hashlib.sha256(row["record"].encode()).hexdigest() != row["record_sha256"]:
            raise AuthorityDenied("admission link unavailable for exact retained intent")
        return {**json.loads(row["record"]), "link_sha256": row["record_sha256"]}

    def _guards(self):
        namespace = _quote(self.store.schema) + "." if self.postgres else ""
        size = "octet_length" if self.postgres else "length"
        def encoded(name):
            return size + "(" + (name if self.postgres else "CAST(" + name + " AS BLOB)") + ")"

        # Native task/context IDs allow 128 Unicode characters. Bound the
        # encoded JSON while preserving that existing identifier contract.
        bounds = [encoded("NEW.record") + "<=8192", encoded("NEW.snapshot") + "<=4096"]
        bounds += ["length(NEW." + name + ") BETWEEN 1 AND 128 AND " + encoded("NEW." + name) + "<=512"
                   for name in ("owner_id", "task_id", "agent_id", "operation_id", "reservation_token")]
        bounds += ["length(NEW." + name + ")=64" for name in ("intent_sha256", "action_sha256", "record_sha256")]
        relation = (
            "EXISTS(SELECT 1 FROM " + namespace + "task_intents_v1 i JOIN " + namespace +
            "agent_operations o ON o.agent_id=i.agent_id AND o.operation_id=i.operation_id JOIN " + namespace +
            "operation_reservations r ON r.agent_id=o.agent_id AND r.operation_id=o.operation_id JOIN " + namespace +
            "task_lifecycle_events e ON e.owner_id=i.owner_id AND e.task_id=i.task_id "
            "JOIN " + namespace + "task_lifecycle_snapshots s ON s.owner_id=e.owner_id AND s.task_id=e.task_id "
            "WHERE i.owner_id=NEW.owner_id AND i.task_id=NEW.task_id AND i.agent_id=NEW.agent_id "
            "AND i.operation_id=NEW.operation_id AND i.fingerprint=NEW.intent_sha256 "
            "AND o.fingerprint=NEW.action_sha256 AND o.state='unknown' "
            "AND r.token=NEW.reservation_token AND e.sequence=NEW.event_sequence "
            "AND e.snapshot=NEW.snapshot AND s.snapshot=NEW.snapshot AND s.terminal=0 AND NEW.event_sequence=1)"
        )
        condition = " AND ".join(bounds + [relation])
        if not self.postgres:
            self._execute(
                "CREATE TRIGGER IF NOT EXISTS task_link_bounds_v1 BEFORE INSERT ON task_operation_links_v1 "
                "WHEN NOT(" + condition + ") BEGIN SELECT RAISE(ABORT,'invalid or unbounded task admission link'); END"
            )
            for action in ("UPDATE", "DELETE"):
                self._execute(
                    "CREATE TRIGGER IF NOT EXISTS task_link_immutable_" + action.lower() + "_v1 BEFORE " + action +
                    " ON task_operation_links_v1 BEGIN SELECT RAISE(ABORT,'task admission history is immutable'); END"
                )
                self._execute(
                    "CREATE TRIGGER IF NOT EXISTS task_link_meta_immutable_" + action.lower() + "_v1 BEFORE " + action +
                    " ON task_operation_links_meta_v1 BEGIN SELECT RAISE(ABORT,'task admission schema is immutable'); END"
                )
            return
        function = namespace + "task_link_guard_v1"
        self._execute(
            "CREATE OR REPLACE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql "
            "SET search_path=pg_catalog AS $$ BEGIN IF TG_OP<>'INSERT' THEN "
            "RAISE EXCEPTION 'task admission history is immutable'; END IF; "
            "IF current_setting('transaction_isolation')<>'read committed' OR NOT(" + condition + ") THEN "
            "RAISE EXCEPTION 'invalid or unbounded task admission link'; END IF; RETURN NEW; END $$"
        )
        self._execute("DROP TRIGGER IF EXISTS task_link_guard_v1 ON task_operation_links_v1")
        self._execute(
            "CREATE TRIGGER task_link_guard_v1 BEFORE INSERT OR UPDATE OR DELETE ON task_operation_links_v1 "
            "FOR EACH ROW EXECUTE FUNCTION " + function + "()"
        )
        self._execute("DROP TRIGGER IF EXISTS task_link_truncate_v1 ON task_operation_links_v1")
        self._execute(
            "CREATE TRIGGER task_link_truncate_v1 BEFORE TRUNCATE ON task_operation_links_v1 "
            "FOR EACH STATEMENT EXECUTE FUNCTION " + function + "()"
        )
        self._execute(
            "CREATE OR REPLACE FUNCTION " + namespace + "task_link_meta_guard_v1() RETURNS trigger "
            "LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN "
            "RAISE EXCEPTION 'task admission schema is immutable'; END $$"
        )
        self._execute("DROP TRIGGER IF EXISTS task_link_meta_guard_v1 ON task_operation_links_meta_v1")
        self._execute(
            "CREATE TRIGGER task_link_meta_guard_v1 BEFORE UPDATE OR DELETE OR TRUNCATE ON task_operation_links_meta_v1 "
            "FOR EACH STATEMENT EXECUTE FUNCTION " + namespace + "task_link_meta_guard_v1()"
        )
