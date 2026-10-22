"""Bound the existing append-only checkpoint registry without evicting history.

Stored JSON UTF-8 bytes are counted directly under the audit SQL fence. There
is no cached usage counter to reset or restore independently of checkpoint data.
Limits do not provide external custody or authorize audit retention.
"""
from contextlib import closing
from dataclasses import asdict, dataclass


class CheckpointCapacityDenied(RuntimeError):
    """Unsupported checkpoint capacity policy/schema or registry state."""


@dataclass(frozen=True)
class CheckpointLimits:
    max_records: int = 10_000
    max_bytes: int = 16 * 1024 * 1024
    max_entry_bytes: int = 8 * 1024

    def __post_init__(self):
        for field, ceiling in (("max_records", 100_000), ("max_bytes", 128 * 1024 * 1024),
                               ("max_entry_bytes", 64 * 1024)):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise CheckpointCapacityDenied("positive bounded checkpoint capacity required")
        if self.max_entry_bytes > self.max_bytes:
            raise CheckpointCapacityDenied("checkpoint entry exceeds retained capacity")


TABLE = "checkpoint_capacity_policy_v1"
DEFAULTS = CheckpointLimits()
_RESERVED = ("audit", "audit_holds", "audit_checkpoints", TABLE, "tenant_store_binding")
DDL = (
    "CREATE TABLE IF NOT EXISTS " + TABLE + " ("
    "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL CHECK(version=1),"
    "max_records BIGINT NOT NULL CHECK(max_records BETWEEN 1 AND 100000),"
    "max_bytes BIGINT NOT NULL CHECK(max_bytes BETWEEN 1 AND 134217728),"
    "max_entry_bytes BIGINT NOT NULL CHECK(max_entry_bytes>=1 AND max_entry_bytes<=65536 AND max_entry_bytes<=max_bytes))"
)


def assert_sqlite_namespace(cur):
    """Embedding TEMP objects must not redirect a durable library operation."""
    if cur.execute("SELECT name FROM sqlite_temp_master WHERE name IN (?,?,?,?,?) LIMIT 1", _RESERVED).fetchone():
        raise CheckpointCapacityDenied("reserved checkpoint storage name shadowed by SQLite TEMP object")


def assert_postgres_namespace(cur):
    """A privileged embedding must not redirect durable work to session TEMP."""
    if cur.execute("SELECT relname FROM pg_catalog.pg_class WHERE relnamespace=pg_catalog.pg_my_temp_schema() "
                   "AND relname=ANY(%s) LIMIT 1", (list(_RESERVED),)).fetchone():
        raise CheckpointCapacityDenied("reserved checkpoint storage name shadowed by PostgreSQL TEMP object")


def _read_policy(cur):
    rows = cur.execute("SELECT * FROM " + TABLE).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or type(rows[0]["singleton"]) is not int or rows[0]["singleton"] != 1 or (
            type(rows[0]["version"]) is not int or rows[0]["version"] != 1):
        raise CheckpointCapacityDenied("unsupported checkpoint capacity policy rows")
    CheckpointLimits(**{name: rows[0][name] for name in asdict(DEFAULTS)})
    return dict(rows[0])


def _sqlite_shape(cur, table, expected):
    rows = cur.execute("PRAGMA table_xinfo(" + table + ")").fetchall()
    if tuple((row["name"], row["type"], row["pk"], row["notnull"]) for row in rows) != expected or any(
            row["hidden"] != 0 or row["dflt_value"] is not None for row in rows):
        raise CheckpointCapacityDenied("unsupported checkpoint table schema")
    # INTEGER PRIMARY KEY is the rowid and needs no separate unique index.
    if any(row["unique"] for row in cur.execute("PRAGMA index_list(" + table + ")").fetchall()):
        raise CheckpointCapacityDenied("unsupported checkpoint unique key schema")


def _sqlite_sql(sql):
    return "".join(sql.replace("IF NOT EXISTS ", "").split()).rstrip(";").casefold()


def _sqlite_trigger(cur, sql, *, install=True):
    name = sql.split()[5]
    old = cur.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).fetchone()
    if old and _sqlite_sql(old["sql"]) != _sqlite_sql(sql):
        raise CheckpointCapacityDenied("modified checkpoint capacity trigger")
    if not install and not old:
        raise CheckpointCapacityDenied("missing checkpoint capacity trigger")
    if install:
        cur.execute(sql)


def _sqlite_metadata(cur):
    assert_sqlite_namespace(cur)
    if cur.execute("PRAGMA encoding").fetchone()["encoding"] != "UTF-8":
        raise CheckpointCapacityDenied("checkpoint capacity requires UTF-8 SQLite storage")
    _sqlite_shape(cur, TABLE, (("singleton", "INTEGER", 1, 0), ("version", "INTEGER", 0, 1),
                              ("max_records", "BIGINT", 0, 1), ("max_bytes", "BIGINT", 0, 1),
                              ("max_entry_bytes", "BIGINT", 0, 1)))
    _sqlite_shape(cur, "audit_checkpoints", (("seq", "INTEGER", 1, 0), ("data", "TEXT", 0, 1)))
    for table, expected in ((TABLE, DDL), ("audit_checkpoints", "CREATE TABLE audit_checkpoints(seq INTEGER PRIMARY KEY,data TEXT NOT NULL)")):
        actual_ddl = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()["sql"]
        if _sqlite_sql(actual_ddl) != _sqlite_sql(expected):
            raise CheckpointCapacityDenied("unsupported checkpoint table constraints")
    if cur.execute("SELECT 1 FROM audit_checkpoints WHERE typeof(data)<>'text' OR typeof(seq)<>'integer' OR seq<0 LIMIT 1").fetchone():
        raise CheckpointCapacityDenied("unsupported historical checkpoint value types")


def _sqlite_statements():
    # Fail before SQLite may choose REPLACE/IGNORE and erase a prior checkpoint.
    statements = ["CREATE TRIGGER IF NOT EXISTS checkpoint_capacity_duplicate_v1 BEFORE INSERT ON audit_checkpoints "
                "WHEN EXISTS(SELECT 1 FROM audit_checkpoints WHERE seq=NEW.seq) BEGIN "
                "SELECT RAISE(ABORT,'checkpoint sequence already exists'); END",
                "CREATE TRIGGER IF NOT EXISTS checkpoint_capacity_insert_v1 AFTER INSERT ON audit_checkpoints BEGIN "
                "INSERT INTO " + TABLE + " SELECT 1,1,10000,16777216,8192 "
                "WHERE NOT EXISTS(SELECT 1 FROM " + TABLE + " WHERE singleton=1); "
                "SELECT CASE WHEN typeof(NEW.data)<>'text' OR typeof(NEW.seq)<>'integer' OR NEW.seq<0 OR "
                "(SELECT count(*) FROM " + TABLE + ")<>1 OR "
                "(SELECT typeof(singleton)<>'integer' OR singleton<>1 OR typeof(version)<>'integer' OR version<>1 OR "
                "typeof(max_records)<>'integer' OR max_records<1 OR max_records>100000 OR "
                "typeof(max_bytes)<>'integer' OR max_bytes<1 OR max_bytes>134217728 OR "
                "typeof(max_entry_bytes)<>'integer' OR max_entry_bytes<1 OR max_entry_bytes>65536 OR "
                "max_entry_bytes>max_bytes FROM " + TABLE + " WHERE singleton=1) "
                "THEN RAISE(ABORT,'invalid checkpoint capacity policy or row') END; "
                "SELECT CASE WHEN (SELECT count(*) FROM audit_checkpoints)>(SELECT max_records FROM " + TABLE + ") OR "
                "(SELECT coalesce(sum(length(CAST(data AS BLOB))),0) FROM audit_checkpoints)>"
                "(SELECT max_bytes FROM " + TABLE + ") OR length(CAST(NEW.data AS BLOB))>"
                "(SELECT max_entry_bytes FROM " + TABLE + ") "
                "THEN RAISE(ABORT,'retained checkpoint capacity reached') END; END"]
    for table, actions in (("audit_checkpoints", ("UPDATE", "DELETE")), (TABLE, ("DELETE",))):
        for action in actions:
            name = "checkpoint_immutable_" + ("policy" if table == TABLE else "history") + "_" + action.lower() + "_v1"
            statements.append("CREATE TRIGGER IF NOT EXISTS " + name + " BEFORE " + action + " ON " + table +
                        " BEGIN SELECT RAISE(ABORT,'checkpoint history and policy cannot be removed or replaced'); END")
    statements.append("CREATE TRIGGER IF NOT EXISTS checkpoint_policy_no_replace_v1 BEFORE INSERT ON " + TABLE +
                    " WHEN EXISTS(SELECT 1 FROM " + TABLE + " WHERE singleton=NEW.singleton) BEGIN "
                    "SELECT RAISE(ABORT,'checkpoint policy already exists'); END")
    return statements


def install_sqlite(cur):
    assert_sqlite_namespace(cur)
    existed = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone() is not None
    cur.execute(DDL)
    _sqlite_metadata(cur)
    statements = _sqlite_statements()
    present = cur.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name IN (" +
                          ",".join("?" for _ in statements) + ")", tuple(sql.split()[5] for sql in statements)).fetchall()
    if existed or present:
        for statement in statements:
            _sqlite_trigger(cur, statement, install=False)
    else:
        for statement in statements:
            _sqlite_trigger(cur, statement)
    _read_policy(cur)


_POSTGRES_FUNCTION_SQL = {
    "agentbridge_checkpoint_capacity_v1": """
        CREATE OR REPLACE FUNCTION agentbridge_checkpoint_capacity_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE p RECORD; n BIGINT; b BIGINT;
        BEGIN
          PERFORM pg_advisory_xact_lock(911001);
          EXECUTE format('SELECT * FROM %I.checkpoint_capacity_policy_v1 WHERE singleton=1', TG_TABLE_SCHEMA) INTO p;
          IF p.singleton IS NULL THEN
            EXECUTE format('INSERT INTO %I.checkpoint_capacity_policy_v1 VALUES(1,1,10000,16777216,8192)', TG_TABLE_SCHEMA);
            EXECUTE format('SELECT * FROM %I.checkpoint_capacity_policy_v1 WHERE singleton=1', TG_TABLE_SCHEMA) INTO p;
          END IF;
          IF p.version<>1 OR p.max_records<1 OR p.max_records>100000 OR p.max_bytes<1 OR p.max_bytes>134217728 OR
             p.max_entry_bytes<1 OR p.max_entry_bytes>65536 OR p.max_entry_bytes>p.max_bytes OR NEW.seq<0 THEN
            RAISE EXCEPTION 'invalid checkpoint capacity policy or row';
          END IF;
          EXECUTE format('SELECT count(*),coalesce(sum(octet_length(data)),0) FROM %I.audit_checkpoints', TG_TABLE_SCHEMA) INTO n,b;
          IF n>p.max_records OR b>p.max_bytes OR octet_length(NEW.data)>p.max_entry_bytes THEN
            RAISE EXCEPTION 'retained checkpoint capacity reached';
          END IF;
          RETURN NULL;
        END $$
    """,
    "agentbridge_checkpoint_immutable_v1": """CREATE OR REPLACE FUNCTION agentbridge_checkpoint_immutable_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'checkpoint history and policy cannot be removed or replaced'; END $$""",
}


def _postgres_shape(cur, table, expected, key):
    relation = cur.execute(
        "SELECT c.relkind,c.relpersistence FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() AND c.relname=%s", (table,),
    ).fetchone()
    if relation is None or relation["relkind"] != "r" or relation["relpersistence"] != "p":
        raise CheckpointCapacityDenied("checkpoint storage requires ordinary permanent PostgreSQL tables")
    rows = cur.execute(
        "SELECT column_name,data_type,is_nullable,column_default,is_identity,is_generated FROM information_schema.columns WHERE "
        "table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position", (table,),
    ).fetchall()
    if tuple((row["column_name"], row["data_type"]) for row in rows) != expected or any(
            row["is_nullable"] != "NO" or row["column_default"] is not None or
            row["is_identity"] != "NO" or row["is_generated"] != "NEVER" for row in rows):
        raise CheckpointCapacityDenied("unsupported checkpoint table schema")
    indexes = cur.execute(
        "SELECT i.indisprimary,i.indisvalid,i.indisready,i.indnatts,i.indnkeyatts,"
        "i.indpred IS NULL AS no_predicate,i.indexprs IS NULL AS no_expression,"
        "ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum,position) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.position) AS fields "
        "FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname=current_schema() AND t.relname=%s AND i.indisunique", (table,),
    ).fetchall()
    if len(indexes) != 1 or not all(indexes[0][name] for name in (
            "indisprimary", "indisvalid", "indisready", "no_predicate", "no_expression")) or (
            indexes[0]["indnatts"], indexes[0]["indnkeyatts"], indexes[0]["fields"]) != (1, 1, [key]):
        raise CheckpointCapacityDenied("unsupported checkpoint unique key schema")
    constraints = cur.execute(
        "SELECT contype,pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
        "JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname=current_schema() AND t.relname=%s", (table,),
    ).fetchall()
    if any(row["contype"] not in ("p", "c") for row in constraints):
        raise CheckpointCapacityDenied("unsupported checkpoint table constraints")
    checks = ["".join(row["definition"].split()).replace("(", "").replace(")", "").casefold()
              for row in constraints if row["contype"] == "c"]
    expected_checks = {"checksingleton=1", "checkversion=1", "checkmax_records>=1andmax_records<=100000",
                       "checkmax_bytes>=1andmax_bytes<=134217728",
                       "checkmax_entry_bytes>=1andmax_entry_bytes<=65536andmax_entry_bytes<=max_bytes"} if table == TABLE else set()
    if len(checks) != len(expected_checks) or set(checks) != expected_checks:
        raise CheckpointCapacityDenied("unsupported checkpoint table constraints")


def _postgres_installed(cur, *, allow_new=False):
    """Accept initial bootstrap or the exact complete installed trigger contract."""
    functions = cur.execute(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname=current_schema() AND p.proname=ANY(%s)", (list(_POSTGRES_FUNCTION_SQL),),
    ).fetchall()
    triggers = cur.execute(
        "SELECT t.relname AS table_name,g.tgname,g.tgtype,g.tgenabled,g.tgattr::text AS attributes,"
        "g.tgqual IS NULL AS no_condition,g.tgargs AS arguments,g.tgnargs,g.tgisinternal,"
        "g.tgconstraint,g.tgoldtable,g.tgnewtable,p.proname AS function_name,fn.nspname AS function_schema "
        "FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "JOIN pg_proc p ON p.oid=g.tgfoid JOIN pg_namespace fn ON fn.oid=p.pronamespace "
        "WHERE n.nspname=current_schema() AND t.relname=ANY(%s) AND g.tgname=ANY(%s)",
        ([TABLE, "audit_checkpoints"], ["checkpoint_capacity_fence_v1", "checkpoint_immutable_v1", "checkpoint_capacity_insert_v1"]),
    ).fetchall()
    if not functions and not triggers and allow_new:
        return False
    qualified_postgres_routines(cur)
    from .audit_capacity import AuditCapacityDenied
    from .audit_capacity import qualified_postgres_routines as audit_routines
    try:
        audit_routines(cur)
    except AuditCapacityDenied as exc:
        raise CheckpointCapacityDenied("unsupported shared checkpoint audit fence") from exc
    expected = {
        (TABLE, "checkpoint_capacity_fence_v1"): (30, "agentbridge_audit_capacity_fence_v1"),
        ("audit_checkpoints", "checkpoint_capacity_fence_v1"): (30, "agentbridge_audit_capacity_fence_v1"),
        (TABLE, "checkpoint_immutable_v1"): (42, "agentbridge_checkpoint_immutable_v1"),
        ("audit_checkpoints", "checkpoint_immutable_v1"): (58, "agentbridge_checkpoint_immutable_v1"),
        ("audit_checkpoints", "checkpoint_capacity_insert_v1"): (5, "agentbridge_checkpoint_capacity_v1"),
    }
    actual = {(row["table_name"], row["tgname"]): row for row in triggers}
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise CheckpointCapacityDenied("missing or unsupported checkpoint capacity triggers")
    schema = cur.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    for key, (kind, function) in expected.items():
        row = actual[key]
        if (row["tgtype"] != kind or row["tgenabled"] != "O" or row["attributes"] != "" or
                not row["no_condition"] or bytes(row["arguments"]) != b"" or row["tgnargs"] != 0 or
                row["tgisinternal"] or row["tgconstraint"] != 0 or row["tgoldtable"] is not None or
                row["tgnewtable"] is not None or row["function_name"] != function or row["function_schema"] != schema):
            raise CheckpointCapacityDenied("modified checkpoint capacity trigger")
    return True


def install_postgres(cur):
    assert_postgres_namespace(cur)
    if cur.execute("SHOW server_encoding").fetchone()["server_encoding"] != "UTF8":
        raise CheckpointCapacityDenied("checkpoint capacity requires UTF-8 PostgreSQL storage")
    existed = cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=%s", (TABLE,)).fetchone() is not None
    cur.execute(DDL)
    _postgres_shape(cur, TABLE, (("singleton", "integer"), ("version", "integer"), ("max_records", "bigint"),
                                 ("max_bytes", "bigint"), ("max_entry_bytes", "bigint")), "singleton")
    _postgres_shape(cur, "audit_checkpoints", (("seq", "bigint"), ("data", "text")), "seq")
    if _postgres_installed(cur, allow_new=not existed):
        _read_policy(cur)
        return
    for sql in _POSTGRES_FUNCTION_SQL.values():
        cur.execute(sql)
    for table in (TABLE, "audit_checkpoints"):
        trigger = "checkpoint_capacity_fence_v1"
        cur.execute("DROP TRIGGER IF EXISTS " + trigger + " ON " + table)
        # Reuse the already installed audit fence function and its established
        # BEFORE STATEMENT lock ordering, before unique-index ownership.
        cur.execute("CREATE TRIGGER " + trigger + " BEFORE INSERT OR UPDATE OR DELETE ON " + table +
                    " FOR EACH STATEMENT EXECUTE FUNCTION agentbridge_audit_capacity_fence_v1()")
        trigger = "checkpoint_immutable_v1"
        cur.execute("DROP TRIGGER IF EXISTS " + trigger + " ON " + table)
        actions = "DELETE OR TRUNCATE" if table == TABLE else "UPDATE OR DELETE OR TRUNCATE"
        cur.execute("CREATE TRIGGER " + trigger + " BEFORE " + actions + " ON " + table +
                    " FOR EACH STATEMENT EXECUTE FUNCTION agentbridge_checkpoint_immutable_v1()")
    cur.execute("DROP TRIGGER IF EXISTS checkpoint_capacity_insert_v1 ON audit_checkpoints")
    cur.execute("CREATE TRIGGER checkpoint_capacity_insert_v1 AFTER INSERT ON audit_checkpoints "
                "FOR EACH ROW EXECUTE FUNCTION agentbridge_checkpoint_capacity_v1()")
    _postgres_installed(cur)
    _read_policy(cur)


def qualified_postgres_routines(cur):
    """Qualify exact checkpoint routines and safe attributes for offline restore."""
    names = list(_POSTGRES_FUNCTION_SQL)
    rows = cur.execute(
        "SELECT p.proname,p.prosrc,p.pronargs,p.prorettype::regtype::text AS result,p.prokind,"
        "p.prosecdef,p.provolatile,p.proleakproof,p.proisstrict,p.proparallel,p.proretset,p.provariadic,"
        "p.proconfig,l.lanname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname=current_schema() AND p.proname=ANY(%s)",
        (names,),
    ).fetchall()
    if len(rows) != len(names) or {row["proname"] for row in rows} != set(names):
        raise CheckpointCapacityDenied("missing or overloaded checkpoint capacity migration routine")
    for row in rows:
        body = _POSTGRES_FUNCTION_SQL[row["proname"]].split("$$")[1]
        if (row["prosrc"] != body or row["pronargs"] != 0 or row["result"] != "trigger" or
                row["prokind"] != "f" or row["lanname"] != "plpgsql" or row["prosecdef"] or
                row["provolatile"] != "v" or row["proleakproof"] or row["proisstrict"] or
                row["proparallel"] != "u" or row["proretset"] or row["provariadic"] != 0 or
                row["proconfig"] != ["search_path=pg_catalog"]):
            raise CheckpointCapacityDenied("modified checkpoint capacity migration routine")
    return names


def verify_snapshot(cur, *, postgres):
    """Read-only verification under the caller's complete offline snapshot locks."""
    if postgres:
        assert_postgres_namespace(cur)
        _postgres_shape(cur, TABLE, (("singleton", "integer"), ("version", "integer"), ("max_records", "bigint"),
                                     ("max_bytes", "bigint"), ("max_entry_bytes", "bigint")), "singleton")
        _postgres_shape(cur, "audit_checkpoints", (("seq", "bigint"), ("data", "text")), "seq")
        if cur.execute("SHOW server_encoding").fetchone()["server_encoding"] != "UTF8":
            raise CheckpointCapacityDenied("checkpoint capacity requires UTF-8 PostgreSQL storage")
        _postgres_installed(cur)
    else:
        _sqlite_metadata(cur)
        for statement in _sqlite_statements():
            _sqlite_trigger(cur, statement, install=False)
    _read_policy(cur)
    size = "octet_length(data)" if postgres else "length(CAST(data AS BLOB))"
    return dict(cur.execute("SELECT count(*) AS records,coalesce(sum(" + size + "),0) AS bytes FROM audit_checkpoints").fetchone())


def verify_if_installed(cur, *, postgres):
    """Distinguish untouched legacy schemas from an incomplete selective restore."""
    if postgres:
        assert_postgres_namespace(cur)
        exists = cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=%s", (TABLE,)).fetchone()
        # Existing checkpoint routines without metadata are already rejected
        # by the migration's exact known-routine allowlist.
    else:
        assert_sqlite_namespace(cur)
        exists = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
        names = tuple(statement.split()[5] for statement in _sqlite_statements())
        if not exists and cur.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name IN (" +
                                      ",".join("?" for _ in names) + ") LIMIT 1", names).fetchone():
            raise CheckpointCapacityDenied("checkpoint capacity metadata missing from installed registry")
    if exists:
        return verify_snapshot(cur, postgres=postgres)
    return None


def policy(store, *, limits=None, audit=None):
    """Trusted library policy; actual usage is read in the same SQL transaction."""
    from .store import PostgresStore, sql_atomic

    if limits is not None and not isinstance(limits, CheckpointLimits):
        raise CheckpointCapacityDenied("CheckpointLimits required")
    postgres = isinstance(store, PostgresStore)
    with sql_atomic(store):
        with closing(store._db.cursor()) as cur:
            if postgres:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (911001,))
                assert_postgres_namespace(cur)
            else:
                assert_sqlite_namespace(cur)
            if _read_policy(cur) is None:
                cur.execute("INSERT INTO " + TABLE + " VALUES(1,1,10000,16777216,8192)")
            if limits is not None:
                marker = "%s" if postgres else "?"
                cur.execute("UPDATE " + TABLE + " SET max_records=" + marker + ",max_bytes=" + marker +
                            ",max_entry_bytes=" + marker + " WHERE singleton=1", tuple(asdict(limits).values()))
                if audit is not None:
                    audit()
            if postgres:
                assert_postgres_namespace(cur)
            else:
                assert_sqlite_namespace(cur)
            row = _read_policy(cur)
            size = "octet_length(data)" if postgres else "length(CAST(data AS BLOB))"
            actual = cur.execute("SELECT count(*) AS n,coalesce(sum(" + size + "),0) AS b FROM audit_checkpoints").fetchone()
            return {**row, "used_records": actual["n"], "used_bytes": actual["b"]}
