"""Bounded immutable execution decisions/results; no lease reset or send API."""

from __future__ import annotations

import hashlib
import json

from ..protocols.task_lifecycle import _identifier
from .authority import AuthorityDenied
from .store import PostgresStore, SqliteStore, sql_atomic
from .tenant_store import _install_postgres_guards, _install_sqlite_guards, _quote


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


class TaskExecutionStore:
    """At most one decision, one result and one cancellation request per intent.

    Result JSON consumes the accepted immutable result allowance. Decision and
    control JSON add at most 32 KiB and 4 KiB, plus fixed identifiers/index/backend
    overhead, per retained intent. No table deletes or updates historical rows.
    """

    DECISIONS = "task_execution_decisions_v1"
    RESULTS = "task_execution_results_v1"
    CONTROLS = "task_execution_controls_v1"
    META = "task_execution_meta_v1"
    TABLES = (DECISIONS, RESULTS, CONTROLS)
    COLUMNS = tuple((name, "TEXT") for name in (
        "owner_id", "task_id", "agent_id", "operation_id", "admission_link_sha256",
        "kind", "record", "record_sha256",
    ))
    META_COLUMNS = (("singleton", "INTEGER"), ("version", "INTEGER"), ("schema_sha256", "TEXT"))
    DECISION_BYTES = 32768
    CONTROL_BYTES = 4096
    SCHEMA_SHA256 = _digest({"version": 1, "columns": COLUMNS, "metadata": META_COLUMNS,
                             "decision_bytes": DECISION_BYTES, "control_bytes": CONTROL_BYTES,
                             "result_bytes": "accepted immutable result_limit_bytes",
                             "primary": ["owner_id", "task_id"], "unique": ["agent_id", "operation_id"]})

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
                    "ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname IN (?,?,?,?)",
                    (*self.TABLES, self.META),
                ).fetchall()
                expected_kind = "r"
            else:
                rows = self._execute("SELECT name,type AS kind FROM sqlite_master WHERE name IN (?,?,?,?)",
                                     (*self.TABLES, self.META)).fetchall()
                expected_kind = "table"
            objects = {row["name"] for row in rows if row["kind"] == expected_kind}
            if len(objects) != len(rows) or (objects and objects != {*self.TABLES, self.META}):
                raise AuthorityDenied("partial or unsupported task execution schema")
            if not objects:
                for table in self.TABLES:
                    self._execute("CREATE TABLE " + table + "(" + ",".join(
                        name + " " + kind + " NOT NULL" for name, kind in self.COLUMNS
                    ) + ",PRIMARY KEY(owner_id,task_id),UNIQUE(agent_id,operation_id))")
                self._execute("CREATE TABLE " + self.META + "(singleton INTEGER NOT NULL PRIMARY KEY "
                              "CHECK(singleton=1),version INTEGER NOT NULL,schema_sha256 TEXT NOT NULL)")
                self._execute("INSERT INTO " + self.META + " VALUES(1,1,?)", (self.SCHEMA_SHA256,))
            for table in (*self.TABLES, self.META):
                self._qualify(table)
            rows = self._execute("SELECT * FROM " + self.META).fetchall()
            if len(rows) != 1 or dict(rows[0]) != {"singleton": 1, "version": 1, "schema_sha256": self.SCHEMA_SHA256}:
                raise AuthorityDenied("unsupported task execution schema version or digest")
            self._guards()
            if self.postgres:
                with store._db.cursor() as cur:
                    _install_postgres_guards(cur, store.schema, (*self.TABLES, self.META))
            else:
                _install_sqlite_guards(store._db, (*self.TABLES, self.META))

    def _execute(self, query, values=()):
        return self.store._db.execute(query.replace("?", "%s") if self.postgres else query, values)

    def _mode(self):
        if not self.postgres and self._execute(
            "SELECT 1 FROM temp.sqlite_master WHERE name IN (?,?,?,?) LIMIT 1", (*self.TABLES, self.META),
        ).fetchone() is not None:
            # TEMP relations take precedence over unqualified main relations.
            # Refuse them under the same store lock as every subsequent read
            # or write: a committed attempt must survive connection/process loss.
            raise AuthorityDenied("TEMP execution schema shadows are unsupported")
        if self.postgres and self._execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
            raise AuthorityDenied("queued execution requires PostgreSQL READ COMMITTED")

    def _qualify(self, table):
        expected = self.META_COLUMNS if table == self.META else self.COLUMNS
        primary = ("singleton",) if table == self.META else ("owner_id", "task_id")
        required = {primary} if table == self.META else {primary, ("agent_id", "operation_id")}
        if self.postgres:
            rows = self._execute("SELECT column_name AS name,data_type AS type,is_nullable "
                                 "FROM information_schema.columns WHERE table_schema=current_schema() "
                                 "AND table_name=? ORDER BY ordinal_position", (table,)).fetchall()
            columns = [(row["name"], row["type"].upper()) for row in rows if row["is_nullable"] == "NO"]
            keys = self._execute(
                "SELECT i.indisprimary AS primary_key,i.indisvalid AND i.indisready AND i.indpred IS NULL "
                "AND i.indexprs IS NULL AND i.indnkeyatts=i.indnatts AS supported,"
                "ARRAY(SELECT a.attname::text FROM unnest(i.indkey) WITH ORDINALITY k(attnum,pos) "
                "LEFT JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.pos) AS cols "
                "FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                "WHERE n.nspname=current_schema() AND t.relname=? AND i.indisunique", (table,),
            ).fetchall()
            if any(not row["supported"] for row in keys):
                raise AuthorityDenied("unsupported task execution schema shape")
            primaries = {tuple(row["cols"]) for row in keys if row["primary_key"]}
            unique = {tuple(row["cols"]) for row in keys}
            count = len(keys)
        else:
            rows = self._execute("PRAGMA table_info(" + _quote(table) + ")").fetchall()
            columns = [(row["name"], row["type"].upper()) for row in rows if row["notnull"]]
            primaries = {tuple(row["name"] for row in sorted(rows, key=lambda row: row["pk"]) if row["pk"])}
            unique, count, indexed_primary = set(primaries), 0, False
            for index in self._execute("PRAGMA index_list(" + _quote(table) + ")").fetchall():
                if index["unique"]:
                    names = tuple(row["name"] for row in self._execute("PRAGMA index_info(" + _quote(index["name"]) + ")").fetchall())
                    if index["partial"] or None in names:
                        raise AuthorityDenied("unsupported task execution schema shape")
                    unique.add(names)
                    count += 1
                    indexed_primary |= index["origin"] == "pk"
            if not indexed_primary:
                count += len(primaries)
        if len(rows) != len(expected) or columns != list(expected) or primaries != {primary} or unique != required or count != len(required):
            raise AuthorityDenied("unsupported task execution schema shape")

    def decision(self, owner_id, task_id):
        return self._get(self.DECISIONS, owner_id, task_id)

    def result(self, owner_id, task_id):
        return self._get(self.RESULTS, owner_id, task_id)

    def cancellation(self, owner_id, task_id):
        return self._get(self.CONTROLS, owner_id, task_id)

    def _get(self, table, owner_id, task_id):
        _identifier(owner_id, "owner_id")
        _identifier(task_id, "task_id")
        self.store.assert_scope()
        with self.store._lock:
            self._mode()
            row = self._execute("SELECT * FROM " + table + " WHERE owner_id=? AND task_id=?", (owner_id, task_id)).fetchone()
        if row is None:
            return None
        try:
            record = json.loads(row["record"])
            if hashlib.sha256(row["record"].encode()).hexdigest() != row["record_sha256"] or any(
                record[name] != row[name] for name in ("owner_id", "task_id", "agent_id", "operation_id", "admission_link_sha256")
            ):
                raise ValueError("execution history mismatch")
        except (TypeError, KeyError, ValueError) as exc:
            raise AuthorityDenied("task execution history unavailable") from exc
        return {**record, "record_sha256": row["record_sha256"]}

    def insert_decision(self, record):
        return self._put(self.DECISIONS, record, record["kind"])

    def insert_result(self, record):
        return self._put(self.RESULTS, record, record["outcome"])

    def insert_cancellation(self, record):
        return self._put(self.CONTROLS, record, "cancel-request")

    def _put(self, table, record, kind):
        with self.store._lock:
            self.store.assert_scope()
            self._mode()
            if self.postgres:
                from psycopg.pq import TransactionStatus
                active = self.store._db.info.transaction_status == TransactionStatus.INTRANS
            else:
                active = self.store._db.in_transaction
            if not active:
                raise RuntimeError("execution history requires the owned tenant transaction")
            raw = _json(record)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            self._execute("INSERT INTO " + table + " VALUES(?,?,?,?,?,?,?,?)", (
                record["owner_id"], record["task_id"], record["agent_id"], record["operation_id"],
                record["admission_link_sha256"], kind, raw, digest,
            ))
            return {**record, "record_sha256": digest}

    def _guards(self):
        namespace = _quote(self.store.schema) + "." if self.postgres else ""
        size = (lambda name: "octet_length(" + name + ")") if self.postgres else (lambda name: "length(CAST(" + name + " AS BLOB))")
        for table in self.TABLES:
            conditions = ["length(NEW." + name + ") BETWEEN 1 AND 128 AND " + size("NEW." + name) + "<=512"
                          for name in ("owner_id", "task_id", "agent_id", "operation_id")]
            conditions += ["length(NEW.admission_link_sha256)=64", "length(NEW.record_sha256)=64"]
            relation = "EXISTS(SELECT 1 FROM " + namespace + "task_operation_links_v1 a WHERE a.owner_id=NEW.owner_id " \
                       "AND a.task_id=NEW.task_id AND a.agent_id=NEW.agent_id AND a.operation_id=NEW.operation_id " \
                       "AND a.record_sha256=NEW.admission_link_sha256)"
            conditions.append(relation)
            if table == self.DECISIONS:
                conditions += ["NEW.kind IN ('attempt','closed')", size("NEW.record") + "<=" + str(self.DECISION_BYTES)]
            else:
                conditions += ["EXISTS(SELECT 1 FROM " + namespace + self.DECISIONS + " d WHERE d.owner_id=NEW.owner_id "
                               "AND d.task_id=NEW.task_id AND d.admission_link_sha256=NEW.admission_link_sha256 AND d.kind='attempt')"]
                if table == self.RESULTS:
                    conditions += ["NEW.kind IN ('succeeded','failed')", "EXISTS(SELECT 1 FROM " + namespace +
                                   "task_intents_v1 i WHERE i.owner_id=NEW.owner_id AND i.task_id=NEW.task_id AND " +
                                   size("NEW.record") + "<=i.result_limit_bytes)"]
                else:
                    conditions += ["NEW.kind='cancel-request'", size("NEW.record") + "<=" + str(self.CONTROL_BYTES)]
            condition = " AND ".join(conditions)
            if self.postgres:
                function = namespace + table + "_guard"
                self._execute("CREATE OR REPLACE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql "
                              "SET search_path=pg_catalog AS $$ BEGIN IF TG_OP<>'INSERT' THEN "
                              "RAISE EXCEPTION 'task execution history is immutable'; END IF; IF NOT(" + condition + ") THEN "
                              "RAISE EXCEPTION 'invalid, immutable or unbounded task execution history'; END IF; RETURN NEW; END $$")
                self._execute("DROP TRIGGER IF EXISTS execution_guard ON " + table)
                self._execute("CREATE TRIGGER execution_guard BEFORE INSERT OR UPDATE OR DELETE ON " + table +
                              " FOR EACH ROW EXECUTE FUNCTION " + function + "()")
                self._execute("DROP TRIGGER IF EXISTS execution_truncate ON " + table)
                self._execute("CREATE TRIGGER execution_truncate BEFORE TRUNCATE ON " + table +
                              " FOR EACH STATEMENT EXECUTE FUNCTION " + function + "()")
            else:
                self._execute("CREATE TRIGGER IF NOT EXISTS " + table + "_bounds BEFORE INSERT ON " + table +
                              " WHEN NOT(" + condition + ") BEGIN SELECT RAISE(ABORT,'invalid or unbounded task execution history'); END")
                for action in ("UPDATE", "DELETE"):
                    self._execute("CREATE TRIGGER IF NOT EXISTS " + table + "_" + action.lower() + " BEFORE " + action +
                                  " ON " + table + " BEGIN SELECT RAISE(ABORT,'task execution history is immutable'); END")
        if self.postgres:
            function = namespace + "task_execution_meta_immutable"
            self._execute("CREATE OR REPLACE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql "
                          "SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'task execution schema is immutable'; END $$")
            self._execute("DROP TRIGGER IF EXISTS execution_meta_guard ON " + self.META)
            self._execute("CREATE TRIGGER execution_meta_guard BEFORE UPDATE OR DELETE OR TRUNCATE ON " + self.META +
                          " FOR EACH STATEMENT EXECUTE FUNCTION " + function + "()")
        else:
            for action in ("UPDATE", "DELETE"):
                self._execute("CREATE TRIGGER IF NOT EXISTS execution_meta_" + action.lower() + " BEFORE " + action +
                              " ON " + self.META + " BEGIN SELECT RAISE(ABORT,'task execution schema is immutable'); END")
