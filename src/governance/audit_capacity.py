"""Retained audit payload capacity at the existing SQL write boundary.

Limits count stored UTF-8 JSON bytes, excluding database/index/WAL overhead.
Saturation rejects writes atomically; it never evicts evidence. These local
resource controls do not provide independent custody or authorize retention.
"""
from dataclasses import asdict, dataclass


class AuditCapacityDenied(RuntimeError):
    """Invalid policy, exhausted retained capacity or unsupported metadata."""


@dataclass(frozen=True)
class AuditLimits:
    max_records: int = 100_000
    max_bytes: int = 64 * 1024 * 1024
    max_entry_bytes: int = 16 * 1024

    def __post_init__(self):
        for field, ceiling in (("max_records", 1_000_000), ("max_bytes", 1024**3),
                               ("max_entry_bytes", 64 * 1024)):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise AuditCapacityDenied("positive bounded audit capacity required")
        if self.max_entry_bytes > self.max_bytes:
            raise AuditCapacityDenied("audit entry capacity exceeds retained byte capacity")


TABLE = "audit_capacity_policy_v1"
DDL = ("CREATE TABLE IF NOT EXISTS " + TABLE + " ("
       "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL,"
       "max_records BIGINT NOT NULL,max_bytes BIGINT NOT NULL,max_entry_bytes BIGINT NOT NULL,"
       "used_records BIGINT NOT NULL,used_bytes BIGINT NOT NULL)")
DEFAULTS = AuditLimits()


def _validate(row):
    if row is None or row["version"] != 1:
        raise AuditCapacityDenied("missing or unsupported audit capacity policy")
    limits = AuditLimits(**{field: row[field] for field in asdict(DEFAULTS)})
    if any(type(row[field]) is not int or row[field] < 0 for field in ("used_records", "used_bytes")):
        raise AuditCapacityDenied("invalid retained audit capacity counters")
    return limits


def verify_retained_usage(cur, *, postgres):
    """Verify persisted counters against real stored bytes without resetting them.

    The caller owns the SQLite write transaction, PostgreSQL audit fence, or
    the migration's exclusive table locks.
    Empty metadata is only the lazy legacy-upgrade state. Restore acceptance
    still requires a complete verified same-version backup, not selected rows.
    Already-over-limit history remains available for inspection and migration.
    """
    rows = cur.execute("SELECT * FROM " + TABLE).fetchall()
    if not rows:
        return
    if len(rows) != 1 or rows[0]["singleton"] != 1:
        raise AuditCapacityDenied("unsupported audit capacity policy rows")
    row = rows[0]
    _validate(row)
    size = "octet_length(entry)" if postgres else "length(CAST(entry AS BLOB))"
    actual = cur.execute("SELECT count(*) AS n,coalesce(sum(" + size + "),0) AS b FROM audit").fetchone()
    if row["used_records"] != actual["n"] or row["used_bytes"] != actual["b"]:
        raise AuditCapacityDenied("retained audit counters do not match stored history")


def install_sqlite(cur):
    """Empty metadata preserves first tenant binding; first write accounts old rows."""
    cur.execute(DDL)
    columns = cur.execute("PRAGMA table_info(" + TABLE + ")").fetchall()
    expected = (("singleton", "INTEGER", 1, 0), ("version", "INTEGER", 0, 1), ("max_records", "BIGINT", 0, 1),
                ("max_bytes", "BIGINT", 0, 1), ("max_entry_bytes", "BIGINT", 0, 1),
                ("used_records", "BIGINT", 0, 1), ("used_bytes", "BIGINT", 0, 1))
    if tuple((row["name"], row["type"], row["pk"], row["notnull"]) for row in columns) != expected:
        raise AuditCapacityDenied("unsupported audit capacity schema")
    # REPLACE can suppress DELETE triggers on an older connection with
    # recursive_triggers disabled. Reject identity collisions before SQLite
    # chooses IGNORE/REPLACE, preserving both evidence and exact counters.
    cur.execute("CREATE TRIGGER IF NOT EXISTS audit_capacity_no_replace_v1 BEFORE INSERT ON audit "
                "WHEN EXISTS(SELECT 1 FROM audit WHERE seq=NEW.seq) BEGIN "
                "SELECT RAISE(ABORT,'audit sequence already exists; replacement forbidden'); END")
    # AFTER INSERT avoids charging PostgreSQL-style duplicate/no-op inserts.
    # SQLite's trigger performs the same atomic check, including direct inserts
    # from workers that predate this application code.
    cur.execute("CREATE TRIGGER IF NOT EXISTS audit_capacity_insert_v1 AFTER INSERT ON audit BEGIN "
                "INSERT INTO " + TABLE + " SELECT 1,1,100000,67108864,16384,"
                "(SELECT count(*) FROM audit WHERE seq<>NEW.seq),"
                "(SELECT coalesce(sum(length(CAST(entry AS BLOB))),0) FROM audit WHERE seq<>NEW.seq) "
                "WHERE NOT EXISTS(SELECT 1 FROM " + TABLE + " WHERE singleton=1); "
                "SELECT CASE WHEN (SELECT version<>1 OR used_records<0 OR used_bytes<0 OR "
                "max_records<1 OR max_records>1000000 OR max_bytes<1 OR max_bytes>1073741824 OR "
                "max_entry_bytes<1 OR max_entry_bytes>65536 OR max_entry_bytes>max_bytes FROM " + TABLE +
                " WHERE singleton=1) THEN RAISE(ABORT,'invalid audit capacity policy') END; "
                "UPDATE " + TABLE + " SET used_records=used_records+1,"
                "used_bytes=used_bytes+length(CAST(NEW.entry AS BLOB)) WHERE singleton=1; "
                "SELECT CASE WHEN (SELECT used_records>max_records OR used_bytes>max_bytes OR "
                "length(CAST(NEW.entry AS BLOB))>max_entry_bytes FROM " + TABLE +
                " WHERE singleton=1) THEN RAISE(ABORT,'retained audit capacity reached') END; END")
    cur.execute("CREATE TRIGGER IF NOT EXISTS audit_capacity_delete_v1 AFTER DELETE ON audit BEGIN "
                "UPDATE " + TABLE + " SET used_records=used_records-1,"
                "used_bytes=used_bytes-length(CAST(OLD.entry AS BLOB)) WHERE singleton=1; END")
    cur.execute("CREATE TRIGGER IF NOT EXISTS audit_capacity_update_v1 AFTER UPDATE ON audit BEGIN "
                "INSERT INTO " + TABLE + " SELECT 1,1,100000,67108864,16384,"
                "(SELECT count(*) FROM audit),"
                "(SELECT coalesce(sum(length(CAST(entry AS BLOB))),0) FROM audit)"
                "-length(CAST(NEW.entry AS BLOB))+length(CAST(OLD.entry AS BLOB)) "
                "WHERE NOT EXISTS(SELECT 1 FROM " + TABLE + " WHERE singleton=1); "
                "UPDATE " + TABLE + " SET used_bytes=used_bytes+length(CAST(NEW.entry AS BLOB))-"
                "length(CAST(OLD.entry AS BLOB)) WHERE singleton=1; "
                "SELECT CASE WHEN (SELECT version<>1 OR used_records<0 OR used_records>max_records OR "
                "used_bytes<0 OR used_bytes>max_bytes OR max_records<1 OR max_records>1000000 OR "
                "max_bytes<1 OR max_bytes>1073741824 OR max_entry_bytes<1 OR max_entry_bytes>65536 OR "
                "max_entry_bytes>max_bytes OR "
                "length(CAST(NEW.entry AS BLOB))>max_entry_bytes FROM " + TABLE +
                " WHERE singleton=1) THEN RAISE(ABORT,'retained audit capacity reached') END; END")
    cur.execute("CREATE TRIGGER IF NOT EXISTS audit_capacity_policy_delete_v1 BEFORE DELETE ON " + TABLE +
                " BEGIN SELECT RAISE(ABORT,'retained audit policy cannot be deleted'); END")


# Exact routine statements are shared with the offline migration qualifier.
_POSTGRES_FUNCTION_SQL = {
    "agentbridge_audit_capacity_fence_v1": """CREATE OR REPLACE FUNCTION agentbridge_audit_capacity_fence_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN PERFORM pg_advisory_xact_lock(911001); RETURN NULL; END $$""",
    "agentbridge_audit_capacity_v1": """
        CREATE OR REPLACE FUNCTION agentbridge_audit_capacity_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE p RECORD; n BIGINT; b BIGINT; size BIGINT;
        BEGIN
          PERFORM pg_advisory_xact_lock(911001);
          EXECUTE format('SELECT * FROM %I.audit_capacity_policy_v1 WHERE singleton=1 FOR UPDATE', TG_TABLE_SCHEMA) INTO p;
          IF TG_OP='DELETE' THEN
            IF p.singleton IS NOT NULL THEN
              EXECUTE format('UPDATE %I.audit_capacity_policy_v1 SET used_records=used_records-1,used_bytes=used_bytes-$1 WHERE singleton=1', TG_TABLE_SCHEMA)
                USING octet_length(OLD.entry);
            END IF;
            RETURN NULL;
          END IF;
          IF p.singleton IS NULL THEN
            EXECUTE format('SELECT count(*),coalesce(sum(octet_length(entry)),0) FROM %I.audit', TG_TABLE_SCHEMA) INTO n,b;
            EXECUTE format('INSERT INTO %I.audit_capacity_policy_v1 VALUES(1,1,100000,67108864,16384,$1,$2)', TG_TABLE_SCHEMA) USING n,b;
          ELSIF TG_OP='INSERT' THEN
            EXECUTE format('UPDATE %I.audit_capacity_policy_v1 SET used_records=used_records+1,used_bytes=used_bytes+$1 WHERE singleton=1', TG_TABLE_SCHEMA) USING octet_length(NEW.entry);
          ELSE
            EXECUTE format('UPDATE %I.audit_capacity_policy_v1 SET used_bytes=used_bytes+$1-$2 WHERE singleton=1', TG_TABLE_SCHEMA) USING octet_length(NEW.entry),octet_length(OLD.entry);
          END IF;
          EXECUTE format('SELECT * FROM %I.audit_capacity_policy_v1 WHERE singleton=1', TG_TABLE_SCHEMA) INTO p;
          size:=octet_length(NEW.entry);
          IF p.version<>1 OR p.used_records<0 OR p.used_bytes<0 OR
             p.max_records<1 OR p.max_records>1000000 OR p.max_bytes<1 OR p.max_bytes>1073741824 OR
             p.max_entry_bytes<1 OR p.max_entry_bytes>65536 OR p.max_entry_bytes>p.max_bytes THEN
            RAISE EXCEPTION 'invalid audit capacity policy';
          END IF;
          IF p.used_records>p.max_records OR p.used_bytes>p.max_bytes OR size>p.max_entry_bytes THEN
            RAISE EXCEPTION 'retained audit capacity reached';
          END IF;
          RETURN NULL;
        END $$
    """,
    "agentbridge_audit_capacity_no_delete_v1": """CREATE OR REPLACE FUNCTION agentbridge_audit_capacity_no_delete_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'retained audit policy and head cannot be deleted or truncated'; END $$""",
}


def install_postgres(cur):
    cur.execute(DDL)
    cur.execute("SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE "
                "table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position", (TABLE,))
    expected = (("singleton", "integer"), ("version", "integer"), ("max_records", "bigint"),
                ("max_bytes", "bigint"), ("max_entry_bytes", "bigint"),
                ("used_records", "bigint"), ("used_bytes", "bigint"))
    columns = cur.fetchall()
    if tuple((row["column_name"], row["data_type"]) for row in columns) != expected or any(
            row["is_nullable"] != "NO" for row in columns):
        raise AuditCapacityDenied("unsupported audit capacity schema")
    cur.execute(
        "SELECT i.indisprimary,i.indisvalid,i.indisready,i.indnatts,i.indnkeyatts,"
        "i.indpred IS NULL AS no_predicate,i.indexprs IS NULL AS no_expression,"
        "ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum,position) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.position) AS fields "
        "FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname=current_schema() AND t.relname=%s AND i.indisunique", (TABLE,),
    )
    indexes = cur.fetchall()
    if len(indexes) != 1 or not all(indexes[0][field] for field in (
            "indisprimary", "indisvalid", "indisready", "no_predicate", "no_expression")) or (
            indexes[0]["indnatts"], indexes[0]["indnkeyatts"], indexes[0]["fields"]) != (1, 1, ["singleton"]):
        raise AuditCapacityDenied("unsupported audit capacity singleton key schema")
    # A row-level AFTER trigger is too late to establish lock order: a raw
    # INSERT can own a unique-index entry while waiting for the audit owner,
    # which then waits for that same entry. Fence BEFORE statement execution.
    cur.execute(_POSTGRES_FUNCTION_SQL["agentbridge_audit_capacity_fence_v1"])
    cur.execute("DROP TRIGGER IF EXISTS audit_capacity_fence_v1 ON audit")
    cur.execute("CREATE TRIGGER audit_capacity_fence_v1 BEFORE INSERT OR UPDATE OR DELETE ON audit "
                "FOR EACH STATEMENT EXECUTE FUNCTION agentbridge_audit_capacity_fence_v1()")
    # Each table's namespace is chosen by the trigger, never a caller search
    # path. The existing audit lock also serializes old direct INSERT paths.
    cur.execute(_POSTGRES_FUNCTION_SQL["agentbridge_audit_capacity_v1"])
    cur.execute("DROP TRIGGER IF EXISTS audit_capacity_write_v1 ON audit")
    cur.execute("CREATE TRIGGER audit_capacity_write_v1 AFTER INSERT OR UPDATE OR DELETE ON audit "
                "FOR EACH ROW EXECUTE FUNCTION agentbridge_audit_capacity_v1()")
    cur.execute(_POSTGRES_FUNCTION_SQL["agentbridge_audit_capacity_no_delete_v1"])
    for table in (TABLE, "audit"):
        name = "audit_capacity_no_delete_v1" if table == TABLE else "audit_capacity_no_truncate_v1"
        actions = "DELETE OR TRUNCATE" if table == TABLE else "TRUNCATE"
        cur.execute("DROP TRIGGER IF EXISTS " + name + " ON " + table)
        cur.execute("CREATE TRIGGER " + name + " BEFORE " + actions + " ON " + table +
                    " FOR EACH STATEMENT EXECUTE FUNCTION agentbridge_audit_capacity_no_delete_v1()")


def qualified_postgres_routines(cur):
    """Offline migration adapter: exact known routines, never a name whitelist.

    Definitions come from the same statements used by bootstrap. Restore may
    legitimately change ownership, but must preserve source, zero arguments,
    trigger result, invoker privileges, volatility and the pinned search path.
    Unknown routines remain the migration framework's explicit rejection.
    """
    names = list(_POSTGRES_FUNCTION_SQL)
    cur.execute(
        "SELECT p.proname,p.prosrc,p.pronargs,p.prorettype::regtype::text AS result,p.prokind,"
        "p.prosecdef,p.provolatile,p.proleakproof,p.proisstrict,p.proparallel,p.proretset,p.provariadic,"
        "p.proconfig,l.lanname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname=current_schema() AND p.proname=ANY(%s)",
        (names,),
    )
    rows = cur.fetchall()
    if len(rows) != len(names) or {row["proname"] for row in rows} != set(names):
        raise AuditCapacityDenied("missing or overloaded audit capacity migration routine")
    for row in rows:
        body = _POSTGRES_FUNCTION_SQL[row["proname"]].split("$$")[1]
        if (row["prosrc"] != body or row["pronargs"] != 0 or row["result"] != "trigger" or
                row["prokind"] != "f" or row["lanname"] != "plpgsql" or row["prosecdef"] or
                row["provolatile"] != "v" or row["proleakproof"] or row["proisstrict"] or
                row["proparallel"] != "u" or row["proretset"] or row["provariadic"] != 0 or
                row["proconfig"] != ["search_path=pg_catalog"]):
            raise AuditCapacityDenied("modified audit capacity migration routine")
    return names


def policy(store, *, limits=None, audit=None):
    """Trusted operator library API; no new HTTP or caller authorization path.

    Lowering a limit preserves historical rows. Already over-limit stores stop
    accepting appends until an operator increases policy or reviewed retention
    becomes eligible. A callback audit joins this transaction and may reject an
    unauditable policy change without leaving the policy partially changed.
    """
    from .store import PostgresStore, sql_atomic

    if limits is not None and not isinstance(limits, AuditLimits):
        raise AuditCapacityDenied("AuditLimits required")
    postgres = isinstance(store, PostgresStore)
    with sql_atomic(store):
        cur = store._db.cursor()
        try:
            if postgres:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (911001,))
            row = cur.execute("SELECT * FROM " + TABLE + " WHERE singleton=1").fetchone()
            if row is None:
                size = "octet_length(entry)" if postgres else "length(CAST(entry AS BLOB))"
                usage = cur.execute("SELECT count(*) AS n,coalesce(sum(" + size + "),0) AS b FROM audit").fetchone()
                marker = "%s" if postgres else "?"
                cur.execute("INSERT INTO " + TABLE + " VALUES(1,1," + ",".join([marker] * 5) + ")",
                            (*asdict(DEFAULTS).values(), usage["n"], usage["b"]))
                row = cur.execute("SELECT * FROM " + TABLE + " WHERE singleton=1").fetchone()
            _validate(row)
            if limits is not None:
                marker = "%s" if postgres else "?"
                cur.execute("UPDATE " + TABLE + " SET max_records=" + marker + ",max_bytes=" + marker +
                            ",max_entry_bytes=" + marker + " WHERE singleton=1", tuple(asdict(limits).values()))
                if audit is not None:
                    audit()
                row = cur.execute("SELECT * FROM " + TABLE + " WHERE singleton=1").fetchone()
            return dict(row)
        finally:
            cur.close()


def retention_guard(cur, *, postgres):
    """Conservative local retention eligibility; never deletes operational evidence.

    The old audit format has no exact per-operation sequence range. Therefore
    ANY retained operation or executable task link keeps the whole audit, even
    after settlement. Nonterminal status-only tasks and reserved budgets also
    protect it. A future narrower release needs explicit reference mapping and
    independently anchored custody, not inference from a terminal task label.
    """
    if postgres:
        tables = {r["tablename"] for r in cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()").fetchall()}
        protected = [table for table in ("agent_operations", "task_operation_links_v1", "budgets",
                                         "task_lifecycle_snapshots") if table in tables]
        if protected:
            # Do not hold the audit lock while waiting for an operation writer,
            # which may itself need the audit lock before it can commit.
            cur.execute("LOCK TABLE " + ",".join(protected) + " IN SHARE MODE")
    else:
        tables = {r["name"] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for table in ("agent_operations", "task_operation_links_v1"):
        if table in tables and cur.execute("SELECT 1 FROM " + table + " LIMIT 1").fetchone():
            raise PermissionError("retained operation evidence blocks audit deletion")
    if "task_lifecycle_snapshots" in tables and cur.execute(
            "SELECT 1 FROM task_lifecycle_snapshots WHERE terminal<>1 LIMIT 1").fetchone():
        raise PermissionError("nonterminal task evidence blocks audit deletion")
    if "budgets" in tables:
        # Query a bounded existence predicate in SQL, never transfer every
        # budget/reservation document into a retention worker.
        pending = ("jsonb_typeof(state::jsonb->'reserved') IS NOT NULL AND "
                   "state::jsonb->'reserved'<>'{}'::jsonb" if postgres else
                   "json_type(state,'$.reserved') IS NOT NULL AND "
                   "(json_type(state,'$.reserved')<>'object' OR json_extract(state,'$.reserved')<>'{}')")
        if cur.execute("SELECT 1 FROM budgets WHERE " + pending + " LIMIT 1").fetchone():
            raise PermissionError("reserved budget evidence blocks audit deletion")
