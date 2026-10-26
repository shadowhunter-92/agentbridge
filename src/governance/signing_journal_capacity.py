"""Retained signing-revision bounds; no eviction or key-state changes.

The namespace budget covers both existing journal domains and actual stored
UTF-8 envelope bytes. Database owners remain trusted. PostgreSQL growth requires
READ COMMITTED and the existing trust lock order before unique-index ownership.
"""

from contextlib import closing
from dataclasses import asdict, dataclass


class SigningJournalCapacityDenied(ValueError):
    pass


@dataclass(frozen=True)
class SigningJournalLimits:
    max_records: int = 10_000
    max_bytes: int = 64 * 1024 * 1024
    max_entry_bytes: int = 256 * 1024

    def __post_init__(self):
        for field, ceiling in (("max_records", 100_000), ("max_bytes", 512 * 1024 * 1024),
                               ("max_entry_bytes", 1024 * 1024)):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise SigningJournalCapacityDenied("positive bounded signing journal capacity required")
        if self.max_entry_bytes > self.max_bytes:
            raise SigningJournalCapacityDenied("signing revision entry exceeds retained capacity")


TABLE = "signing_journal_capacity_policy_v1"
HISTORY = "signing_trust_revisions"
DEFAULTS = SigningJournalLimits()
_RESERVED = (TABLE, HISTORY, "signing_trust_lock_v1", "tenant_store_binding")
HISTORY_DDL = ("CREATE TABLE IF NOT EXISTS signing_trust_revisions ("
               "domain TEXT NOT NULL, revision INTEGER NOT NULL, envelope TEXT NOT NULL, "
               "PRIMARY KEY(domain, revision))")
DDL = (
    "CREATE TABLE IF NOT EXISTS " + TABLE + " ("
    "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL CHECK(version=1),"
    "max_records BIGINT NOT NULL CHECK(max_records BETWEEN 1 AND 100000),"
    "max_bytes BIGINT NOT NULL CHECK(max_bytes BETWEEN 1 AND 536870912),"
    "max_entry_bytes BIGINT NOT NULL CHECK(max_entry_bytes>=1 AND max_entry_bytes<=1048576 AND max_entry_bytes<=max_bytes))"
)


def assert_sqlite_namespace(cur):
    # SQLite identifier identity folds ASCII case, unlike catalog TEXT equality.
    # The reserved names are ASCII; SQLite's native NOCASE matches that identity.
    if cur.execute("SELECT name FROM sqlite_temp_master WHERE name COLLATE NOCASE IN (?,?,?,?) LIMIT 1", _RESERVED).fetchone():
        raise SigningJournalCapacityDenied("reserved signing journal name shadowed by SQLite TEMP object")


def prepare_sqlite(cur):
    """Do not turn a selective history-table loss into a fresh installation."""
    assert_sqlite_namespace(cur)
    installed = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name COLLATE NOCASE=?", (TABLE,)).fetchone()
    if installed and not cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name COLLATE NOCASE=?", (HISTORY,)).fetchone():
        raise SigningJournalCapacityDenied("signing journal history missing from installed capacity policy")


def _sql(sql):
    return "".join(sql.replace("IF NOT EXISTS ", "").split()).rstrip(";").casefold()


def _policy(cur):
    rows = cur.execute("SELECT * FROM " + TABLE).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or type(rows[0]["singleton"]) is not int or rows[0]["singleton"] != 1 or (
            type(rows[0]["version"]) is not int or rows[0]["version"] != 1):
        raise SigningJournalCapacityDenied("unsupported signing journal capacity policy rows")
    SigningJournalLimits(**{name: rows[0][name] for name in asdict(DEFAULTS)})
    return dict(rows[0])


def _metadata(cur):
    assert_sqlite_namespace(cur)
    if cur.execute("PRAGMA encoding").fetchone()["encoding"] != "UTF-8":
        raise SigningJournalCapacityDenied("signing journal capacity requires UTF-8 SQLite storage")
    schemas = {
        HISTORY: (HISTORY_DDL, (("domain", "TEXT", 1, 1), ("revision", "INTEGER", 2, 1), ("envelope", "TEXT", 0, 1))),
        TABLE: (DDL, (("singleton", "INTEGER", 1, 0), ("version", "INTEGER", 0, 1),
                      ("max_records", "BIGINT", 0, 1), ("max_bytes", "BIGINT", 0, 1),
                      ("max_entry_bytes", "BIGINT", 0, 1))),
    }
    for table, (expected_ddl, expected_fields) in schemas.items():
        row = cur.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name COLLATE NOCASE=?", (table,)).fetchone()
        if row and row["name"] != table:
            raise SigningJournalCapacityDenied("noncanonical signing journal table name")
        if not row or _sql(row["sql"]) != _sql(expected_ddl):
            raise SigningJournalCapacityDenied("unsupported signing journal table constraints")
        fields = cur.execute("PRAGMA table_xinfo(" + table + ")").fetchall()
        if tuple((field["name"], field["type"], field["pk"], field["notnull"]) for field in fields) != expected_fields or any(
                field["hidden"] != 0 or field["dflt_value"] is not None for field in fields):
            raise SigningJournalCapacityDenied("unsupported signing journal table schema")
        unique = [index for index in cur.execute("PRAGMA index_list(" + table + ")").fetchall() if index["unique"]]
        if table == TABLE:
            if unique:
                raise SigningJournalCapacityDenied("unsupported signing journal unique key")
        elif len(unique) != 1 or unique[0]["origin"] != "pk" or unique[0]["partial"] != 0 or tuple(
                field["name"] for field in cur.execute("PRAGMA index_info(" + unique[0]["name"] + ")").fetchall()
        ) != ("domain", "revision"):
            raise SigningJournalCapacityDenied("unsupported signing journal unique key")
    if cur.execute("SELECT 1 FROM signing_trust_revisions WHERE typeof(domain)<>'text' OR "
                   "domain NOT IN ('destination','readback') OR typeof(revision)<>'integer' OR "
                   "revision<1 OR revision>2147483647 OR typeof(envelope)<>'text' LIMIT 1").fetchone():
        raise SigningJournalCapacityDenied("unsupported historical signing journal value types")


def _statements():
    statements = [
        "CREATE TRIGGER IF NOT EXISTS signing_capacity_duplicate_v1 BEFORE INSERT ON signing_trust_revisions "
        "WHEN EXISTS(SELECT 1 FROM signing_trust_revisions WHERE domain=NEW.domain AND revision=NEW.revision) "
        "BEGIN SELECT RAISE(ABORT,'signing journal revision already exists'); END",
        "CREATE TRIGGER IF NOT EXISTS signing_capacity_insert_v1 AFTER INSERT ON signing_trust_revisions BEGIN "
        "INSERT INTO " + TABLE + " SELECT 1,1,10000,67108864,262144 WHERE NOT EXISTS(SELECT 1 FROM " + TABLE + "); "
        "SELECT CASE WHEN typeof(NEW.domain)<>'text' OR NEW.domain NOT IN ('destination','readback') OR "
        "typeof(NEW.revision)<>'integer' OR NEW.revision<1 OR NEW.revision>2147483647 OR typeof(NEW.envelope)<>'text' OR "
        "(SELECT count(*) FROM " + TABLE + ")<>1 THEN RAISE(ABORT,'invalid signing journal capacity policy or row') END; "
        "SELECT CASE WHEN (SELECT count(*) FROM signing_trust_revisions)>(SELECT max_records FROM " + TABLE + ") OR "
        "(SELECT coalesce(sum(length(CAST(envelope AS BLOB))),0) FROM signing_trust_revisions)>(SELECT max_bytes FROM " + TABLE + ") OR "
        "length(CAST(NEW.envelope AS BLOB))>(SELECT max_entry_bytes FROM " + TABLE + ") "
        "THEN RAISE(ABORT,'retained signing journal capacity reached') END; END",
        "CREATE TRIGGER IF NOT EXISTS signing_policy_no_replace_v1 BEFORE INSERT ON " + TABLE +
        " WHEN EXISTS(SELECT 1 FROM " + TABLE + " WHERE singleton=NEW.singleton) "
        "BEGIN SELECT RAISE(ABORT,'signing journal policy already exists'); END",
    ]
    condition = ("typeof(NEW.singleton)<>'integer' OR NEW.singleton<>1 OR typeof(NEW.version)<>'integer' OR NEW.version<>1 OR "
                 "typeof(NEW.max_records)<>'integer' OR NEW.max_records<1 OR NEW.max_records>100000 OR "
                 "typeof(NEW.max_bytes)<>'integer' OR NEW.max_bytes<1 OR NEW.max_bytes>536870912 OR "
                 "typeof(NEW.max_entry_bytes)<>'integer' OR NEW.max_entry_bytes<1 OR NEW.max_entry_bytes>1048576 OR "
                 "NEW.max_entry_bytes>NEW.max_bytes")
    for action in ("INSERT", "UPDATE"):
        statements.append("CREATE TRIGGER IF NOT EXISTS signing_policy_validate_" + action.lower() + "_v1 BEFORE " + action +
                          " ON " + TABLE + " WHEN " + condition +
                          " BEGIN SELECT RAISE(ABORT,'invalid signing journal capacity policy'); END")
    for table, actions in ((HISTORY, ("UPDATE", "DELETE")), (TABLE, ("DELETE",))):
        for action in actions:
            name = "signing_immutable_" + ("history" if table == HISTORY else "policy") + "_" + action.lower() + "_v1"
            statements.append("CREATE TRIGGER IF NOT EXISTS " + name + " BEFORE " + action + " ON " + table +
                              " BEGIN SELECT RAISE(ABORT,'signing journal history and policy cannot be removed or replaced'); END")
    return statements


def _triggers(cur, *, install):
    statements = _statements()
    names = tuple(statement.split()[5] for statement in statements)
    installed = cur.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name COLLATE NOCASE IN (" +
                            ",".join("?" for _ in names) + ")", names).fetchall()
    if any(row["name"] not in names for row in installed):
        raise SigningJournalCapacityDenied("noncanonical signing journal capacity trigger name")
    for statement in statements:
        name = statement.split()[5]
        previous = cur.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name COLLATE NOCASE=?", (name,)).fetchone()
        if previous and _sql(previous["sql"]) != _sql(statement):
            raise SigningJournalCapacityDenied("modified signing journal capacity trigger")
        if not previous and not install:
            raise SigningJournalCapacityDenied("missing signing journal capacity trigger")
        if install:
            cur.execute(statement)


def install_sqlite(cur):
    assert_sqlite_namespace(cur)
    exists = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name COLLATE NOCASE=?", (TABLE,)).fetchone() is not None
    names = tuple(statement.split()[5] for statement in _statements())
    present = cur.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name COLLATE NOCASE IN (" +
                          ",".join("?" for _ in names) + ") LIMIT 1", names).fetchone()
    cur.execute(DDL)
    _metadata(cur)
    _triggers(cur, install=not exists and not present)
    _policy(cur)


def verify_if_installed(cur, *, postgres=False):
    """Read-only offline qualification; never rebuild a partial installation."""
    if postgres:
        assert_postgres_namespace(cur)
        exists = cur.execute("SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                             "WHERE n.nspname=current_schema() AND c.relname=%s", (TABLE,)).fetchone()
        if not exists:
            if _postgres_objects(cur)[0] or _postgres_objects(cur)[1]:
                raise SigningJournalCapacityDenied("signing journal capacity metadata missing")
            return None
        _postgres_metadata(cur)
        _postgres_installed(cur)
        _policy(cur)
        return usage(cur, postgres=True)
    assert_sqlite_namespace(cur)
    exists = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name COLLATE NOCASE=?", (TABLE,)).fetchone()
    if not exists:
        names = tuple(statement.split()[5] for statement in _statements())
        if cur.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name COLLATE NOCASE IN (" +
                       ",".join("?" for _ in names) + ") LIMIT 1", names).fetchone():
            raise SigningJournalCapacityDenied("signing journal capacity metadata missing")
        return None
    _metadata(cur)
    _triggers(cur, install=False)
    _policy(cur)
    return usage(cur)


def usage(cur, *, postgres=False):
    size = "octet_length(envelope)" if postgres else "length(CAST(envelope AS BLOB))"
    return dict(cur.execute("SELECT count(*) AS used_records,coalesce(sum(" + size + "),0) AS used_bytes "
                            "FROM signing_trust_revisions").fetchone())


def admit(cur, encoded, *, postgres=False):
    """Early managed-writer denial; SQL triggers also constrain older writers."""
    if postgres:
        assert_postgres_write_context(cur)
    verify_if_installed(cur, postgres=postgres)
    current = _policy(cur)
    limits = asdict(DEFAULTS) if current is None else current
    actual = usage(cur, postgres=postgres)
    if (len(encoded.encode("utf-8")) > limits["max_entry_bytes"] or
            actual["used_records"] + 1 > limits["max_records"] or
            actual["used_bytes"] + len(encoded.encode("utf-8")) > limits["max_bytes"]):
        raise SigningJournalCapacityDenied("retained signing journal capacity reached")


def policy(store, *, limits=None, audit=None):
    from .store import PostgresStore, SqliteStore, sql_atomic

    if not isinstance(store, (SqliteStore, PostgresStore)):
        raise SigningJournalCapacityDenied("durable signing journal store required")
    if limits is not None and not isinstance(limits, SigningJournalLimits):
        raise SigningJournalCapacityDenied("SigningJournalLimits required")
    with sql_atomic(store):
        with closing(store._db.cursor()) as cur:
            postgres = isinstance(store, PostgresStore)
            if postgres:
                lock_postgres_writer(cur)
            verify_if_installed(cur, postgres=postgres)
            if _policy(cur) is None:
                cur.execute("INSERT INTO " + TABLE + " VALUES(1,1,10000,67108864,262144)")
            if limits is not None:
                marker = "%s" if postgres else "?"
                cur.execute("UPDATE " + TABLE + " SET max_records=" + marker + ",max_bytes=" + marker +
                            ",max_entry_bytes=" + marker + " WHERE singleton=1",
                            tuple(asdict(limits).values()))
                if audit is not None:
                    audit()
            if postgres:
                assert_postgres_namespace(cur)
            else:
                assert_sqlite_namespace(cur)
            return {**_policy(cur), **usage(cur, postgres=postgres)}


def assert_postgres_namespace(cur):
    if cur.execute("SELECT relname FROM pg_catalog.pg_class WHERE relnamespace=pg_catalog.pg_my_temp_schema() "
                   "AND relname=ANY(%s) LIMIT 1", (list(_RESERVED),)).fetchone():
        raise SigningJournalCapacityDenied("reserved signing journal name shadowed by PostgreSQL TEMP object")


def assert_postgres_write_context(cur):
    if cur.execute("SELECT current_setting('transaction_isolation') AS isolation").fetchone()["isolation"] != "read committed":
        raise SigningJournalCapacityDenied("signing journal capacity writes require READ COMMITTED isolation")


def prepare_postgres(cur):
    assert_postgres_namespace(cur)
    installed = cur.execute("SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname=current_schema() AND c.relname=%s", (TABLE,)).fetchone()
    if installed:
        relations = cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                "WHERE n.nspname=current_schema() AND c.relname=ANY(%s)",
                                ([HISTORY, "signing_trust_lock_v1"],)).fetchall()
        if {row["relname"] for row in relations} != {HISTORY, "signing_trust_lock_v1"}:
            raise SigningJournalCapacityDenied("signing history or coordination missing from installed capacity policy")


def lock_postgres_writer(cur):
    assert_postgres_namespace(cur)
    assert_postgres_write_context(cur)
    cur.execute("SELECT pg_advisory_xact_lock_shared(%s)", (911005,))
    row = cur.execute("SELECT version FROM signing_trust_lock_v1 WHERE singleton=1 FOR UPDATE").fetchone()
    if not row or row["version"] != 1:
        raise SigningJournalCapacityDenied("missing or unsupported signing coordination policy")


_POSTGRES_FUNCTION_SQL = {
    "agentbridge_signing_capacity_fence_v1": """CREATE OR REPLACE FUNCTION agentbridge_signing_capacity_fence_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v INTEGER;
        BEGIN
          IF current_setting('transaction_isolation')<>'read committed' THEN
            RAISE EXCEPTION 'signing journal capacity writes require READ COMMITTED isolation';
          END IF;
          PERFORM pg_advisory_xact_lock_shared(911005);
          EXECUTE format('SELECT version FROM %I.signing_trust_lock_v1 WHERE singleton=1 FOR UPDATE',TG_TABLE_SCHEMA) INTO v;
          IF v IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'missing or unsupported signing coordination policy'; END IF;
          RETURN NULL;
        END $$""",
    "agentbridge_signing_capacity_insert_v1": """CREATE OR REPLACE FUNCTION agentbridge_signing_capacity_insert_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE p RECORD; n BIGINT; b BIGINT;
        BEGIN
          EXECUTE format('SELECT * FROM %I.signing_journal_capacity_policy_v1 WHERE singleton=1',TG_TABLE_SCHEMA) INTO p;
          IF p.singleton IS NULL THEN
            EXECUTE format('INSERT INTO %I.signing_journal_capacity_policy_v1 VALUES(1,1,10000,67108864,262144)',TG_TABLE_SCHEMA);
            EXECUTE format('SELECT * FROM %I.signing_journal_capacity_policy_v1 WHERE singleton=1',TG_TABLE_SCHEMA) INTO p;
          END IF;
          IF p.version<>1 OR p.max_records<1 OR p.max_records>100000 OR p.max_bytes<1 OR p.max_bytes>536870912 OR
             p.max_entry_bytes<1 OR p.max_entry_bytes>1048576 OR p.max_entry_bytes>p.max_bytes OR
             NEW.domain NOT IN ('destination','readback') OR NEW.revision<1 OR NEW.revision>2147483647 THEN
            RAISE EXCEPTION 'invalid signing journal capacity policy or row';
          END IF;
          EXECUTE format('SELECT count(*),coalesce(sum(octet_length(envelope)),0) FROM %I.signing_trust_revisions',TG_TABLE_SCHEMA) INTO n,b;
          IF n>p.max_records OR b>p.max_bytes OR octet_length(NEW.envelope)>p.max_entry_bytes THEN
            RAISE EXCEPTION 'retained signing journal capacity reached';
          END IF;
          RETURN NULL;
        END $$""",
    "agentbridge_signing_immutable_v1": """CREATE OR REPLACE FUNCTION agentbridge_signing_immutable_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'signing journal history and policy cannot be removed or replaced'; END $$""",
}

_POSTGRES_TRIGGERS = {
    (TABLE, "signing_capacity_fence_v1"): (30, "agentbridge_signing_capacity_fence_v1", "BEFORE INSERT OR UPDATE OR DELETE", "STATEMENT"),
    (HISTORY, "signing_capacity_fence_v1"): (30, "agentbridge_signing_capacity_fence_v1", "BEFORE INSERT OR UPDATE OR DELETE", "STATEMENT"),
    (TABLE, "signing_immutable_v1"): (42, "agentbridge_signing_immutable_v1", "BEFORE DELETE OR TRUNCATE", "STATEMENT"),
    (HISTORY, "signing_immutable_v1"): (58, "agentbridge_signing_immutable_v1", "BEFORE UPDATE OR DELETE OR TRUNCATE", "STATEMENT"),
    (HISTORY, "signing_capacity_insert_v1"): (5, "agentbridge_signing_capacity_insert_v1", "AFTER INSERT", "ROW"),
}


def _postgres_shape(cur, table, fields, key, checks):
    relation = cur.execute("SELECT c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity FROM pg_catalog.pg_class c "
                           "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname=current_schema() AND c.relname=%s", (table,)).fetchone()
    if relation is None or relation["relkind"] != "r" or relation["relpersistence"] != "p":
        raise SigningJournalCapacityDenied("signing journal requires ordinary permanent PostgreSQL tables")
    if relation["relrowsecurity"] or relation["relforcerowsecurity"]:
        raise SigningJournalCapacityDenied("signing journal does not support PostgreSQL row security")
    columns = cur.execute("SELECT column_name,data_type,is_nullable,column_default,is_identity,is_generated "
                          "FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s "
                          "ORDER BY ordinal_position", (table,)).fetchall()
    if tuple((column["column_name"], column["data_type"]) for column in columns) != fields or any(
            column["is_nullable"] != "NO" or column["column_default"] is not None or
            column["is_identity"] != "NO" or column["is_generated"] != "NEVER" for column in columns):
        raise SigningJournalCapacityDenied("unsupported signing journal PostgreSQL columns")
    indexes = cur.execute("SELECT i.indisprimary,i.indisvalid,i.indisready,i.indnatts,i.indnkeyatts,"
                          "i.indpred IS NULL AS no_predicate,i.indexprs IS NULL AS no_expression,"
                          "ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum,position) "
                          "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.position) AS fields "
                          "FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                          "WHERE n.nspname=current_schema() AND t.relname=%s AND i.indisunique", (table,)).fetchall()
    if len(indexes) != 1 or not all(indexes[0][name] for name in (
            "indisprimary", "indisvalid", "indisready", "no_predicate", "no_expression")) or (
            indexes[0]["indnatts"], indexes[0]["indnkeyatts"], indexes[0]["fields"]) != (len(key), len(key), key):
        raise SigningJournalCapacityDenied("unsupported signing journal PostgreSQL unique key")
    constraints = cur.execute("SELECT contype,pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
                              "JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                              "WHERE n.nspname=current_schema() AND t.relname=%s", (table,)).fetchall()
    actual = ["".join(row["definition"].split()).replace("(", "").replace(")", "").casefold()
              for row in constraints if row["contype"] == "c"]
    if any(row["contype"] not in ("p", "c") for row in constraints) or len(actual) != len(checks) or set(actual) != checks:
        raise SigningJournalCapacityDenied("unsupported signing journal PostgreSQL constraints")


def _postgres_metadata(cur):
    assert_postgres_namespace(cur)
    if cur.execute("SHOW server_encoding").fetchone()["server_encoding"] != "UTF8":
        raise SigningJournalCapacityDenied("signing journal capacity requires UTF-8 PostgreSQL storage")
    _postgres_shape(cur, HISTORY, (("domain", "text"), ("revision", "integer"), ("envelope", "text")),
                    ["domain", "revision"], set())
    _postgres_shape(cur, TABLE, (("singleton", "integer"), ("version", "integer"), ("max_records", "bigint"),
                                ("max_bytes", "bigint"), ("max_entry_bytes", "bigint")), ["singleton"],
                    {"checksingleton=1", "checkversion=1", "checkmax_records>=1andmax_records<=100000",
                     "checkmax_bytes>=1andmax_bytes<=536870912",
                     "checkmax_entry_bytes>=1andmax_entry_bytes<=1048576andmax_entry_bytes<=max_bytes"})
    _postgres_shape(cur, "signing_trust_lock_v1", (("singleton", "integer"), ("version", "integer")),
                    ["singleton"], {"checksingleton=1"})
    coordination = cur.execute("SELECT singleton,version FROM signing_trust_lock_v1").fetchall()
    if len(coordination) != 1 or coordination[0]["singleton"] != 1 or coordination[0]["version"] != 1:
        raise SigningJournalCapacityDenied("missing or unsupported signing coordination policy")
    if cur.execute("SELECT 1 FROM signing_trust_revisions WHERE domain NOT IN ('destination','readback') OR "
                   "revision<1 OR revision>2147483647 LIMIT 1").fetchone():
        raise SigningJournalCapacityDenied("unsupported historical signing journal value types")


def qualified_postgres_routines(cur):
    names = list(_POSTGRES_FUNCTION_SQL)
    rows = cur.execute("SELECT p.proname,p.prosrc,p.pronargs,p.prorettype::regtype::text AS result,p.prokind,"
                       "p.prosecdef,p.provolatile,p.proleakproof,p.proisstrict,p.proparallel,p.proretset,p.provariadic,"
                       "p.proconfig,l.lanname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                       "JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname=current_schema() AND p.proname=ANY(%s)",
                       (names,)).fetchall()
    if len(rows) != len(names) or {row["proname"] for row in rows} != set(names):
        raise SigningJournalCapacityDenied("missing or overloaded signing journal capacity routine")
    for row in rows:
        body = _POSTGRES_FUNCTION_SQL[row["proname"]].split("$$")[1]
        if (row["prosrc"] != body or row["pronargs"] != 0 or row["result"] != "trigger" or
                row["prokind"] != "f" or row["lanname"] != "plpgsql" or row["prosecdef"] or
                row["provolatile"] != "v" or row["proleakproof"] or row["proisstrict"] or
                row["proparallel"] != "u" or row["proretset"] or row["provariadic"] != 0 or
                row["proconfig"] != ["search_path=pg_catalog"]):
            raise SigningJournalCapacityDenied("modified signing journal capacity routine")
    return names


def _postgres_objects(cur):
    functions = cur.execute("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                            "WHERE n.nspname=current_schema() AND p.proname=ANY(%s)", (list(_POSTGRES_FUNCTION_SQL),)).fetchall()
    triggers = cur.execute("SELECT t.relname AS table_name,g.tgname,g.tgtype,g.tgenabled,g.tgattr::text AS attributes,"
                           "g.tgqual IS NULL AS no_condition,g.tgargs AS arguments,g.tgnargs,g.tgisinternal,g.tgconstraint,"
                           "g.tgoldtable,g.tgnewtable,p.proname AS function_name,fn.nspname AS function_schema "
                           "FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                           "JOIN pg_proc p ON p.oid=g.tgfoid JOIN pg_namespace fn ON fn.oid=p.pronamespace "
                           "WHERE n.nspname=current_schema() AND t.relname=ANY(%s) AND g.tgname=ANY(%s)",
                           ([TABLE, HISTORY], sorted({name for _, name in _POSTGRES_TRIGGERS}))).fetchall()
    return functions, triggers


def _postgres_installed(cur, *, allow_new=False):
    functions, triggers = _postgres_objects(cur)
    if not functions and not triggers and allow_new:
        return False
    qualified_postgres_routines(cur)
    actual = {(row["table_name"], row["tgname"]): row for row in triggers}
    if len(actual) != len(_POSTGRES_TRIGGERS) or set(actual) != set(_POSTGRES_TRIGGERS):
        raise SigningJournalCapacityDenied("missing or unsupported signing journal capacity triggers")
    schema = cur.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    for key, (kind, function, _, _) in _POSTGRES_TRIGGERS.items():
        row = actual[key]
        if (row["tgtype"] != kind or row["tgenabled"] != "O" or row["attributes"] != "" or not row["no_condition"] or
                bytes(row["arguments"]) != b"" or row["tgnargs"] != 0 or row["tgisinternal"] or row["tgconstraint"] != 0 or
                row["tgoldtable"] is not None or row["tgnewtable"] is not None or
                row["function_name"] != function or row["function_schema"] != schema):
            raise SigningJournalCapacityDenied("modified signing journal capacity trigger")
    return True


def install_postgres(cur):
    assert_postgres_namespace(cur)
    assert_postgres_write_context(cur)
    exists = cur.execute("SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                         "WHERE n.nspname=current_schema() AND c.relname=%s", (TABLE,)).fetchone() is not None
    if exists and not cur.execute("SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                  "WHERE n.nspname=current_schema() AND c.relname=%s", (HISTORY,)).fetchone():
        raise SigningJournalCapacityDenied("signing journal history missing from installed capacity policy")
    cur.execute(DDL)
    _postgres_metadata(cur)
    if not _postgres_installed(cur, allow_new=not exists):
        for statement in _POSTGRES_FUNCTION_SQL.values():
            cur.execute(statement)
        for (table, name), (_, function, events, level) in _POSTGRES_TRIGGERS.items():
            cur.execute("CREATE TRIGGER " + name + " " + events + " ON " + table +
                        " FOR EACH " + level + " EXECUTE FUNCTION " + function + "()")
        _postgres_installed(cur)
    _policy(cur)
