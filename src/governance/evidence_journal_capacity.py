"""Bound retained reconciliation bundles without rewriting or deleting evidence.

The caller owns bootstrap/settlement transactions and tenant authorization.
Limits count actual stored UTF-8 payload, not database/index/WAL overhead. No
cached counters, automatic pruning, refunds, replay or outcome logic live here.
"""
from contextlib import closing
from dataclasses import asdict, dataclass


class EvidenceCapacityDenied(RuntimeError):
    """Unsupported retained evidence capacity policy, namespace or schema."""


@dataclass(frozen=True)
class EvidenceLimits:
    max_records: int = 100_000
    max_bytes: int = 64 * 1024 * 1024
    max_entry_bytes: int = 256 * 1024

    def __post_init__(self):
        for field, ceiling in (("max_records", 1_000_000), ("max_bytes", 1024**3),
                               ("max_entry_bytes", 1024**2)):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise EvidenceCapacityDenied("positive bounded evidence capacity required")
        if self.max_entry_bytes > self.max_bytes:
            raise EvidenceCapacityDenied("evidence entry exceeds retained capacity")


TABLE = "evidence_capacity_policy_v1"
HISTORY = "reconciliation_evidence"
DEFAULTS = EvidenceLimits()
_RESERVED = ("audit", "audit_holds", HISTORY, TABLE, "tenant_store_binding",
             "operation_reconciliations", "reconciliation_readbacks")
DDL = (
    "CREATE TABLE IF NOT EXISTS " + TABLE + " ("
    "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL CHECK(version=1),"
    "max_records BIGINT NOT NULL CHECK(max_records BETWEEN 1 AND 1000000),"
    "max_bytes BIGINT NOT NULL CHECK(max_bytes BETWEEN 1 AND 1073741824),"
    "max_entry_bytes BIGINT NOT NULL CHECK(max_entry_bytes>=1 AND max_entry_bytes<=1048576 AND max_entry_bytes<=max_bytes))"
)
_HISTORY_DDL = ("CREATE TABLE reconciliation_evidence (agent_id TEXT NOT NULL,"
                "operation_id TEXT NOT NULL,bundle TEXT NOT NULL,PRIMARY KEY(agent_id,operation_id))")
_POLICY_SQLITE_SHAPE = (("singleton", "INTEGER", 1, 0), ("version", "INTEGER", 0, 1),
                        ("max_records", "BIGINT", 0, 1), ("max_bytes", "BIGINT", 0, 1),
                        ("max_entry_bytes", "BIGINT", 0, 1))
_HISTORY_SQLITE_SHAPE = (("agent_id", "TEXT", 1, 1), ("operation_id", "TEXT", 2, 1),
                         ("bundle", "TEXT", 0, 1))
_POLICY_PG_SHAPE = (("singleton", "integer"), ("version", "integer"),
                    ("max_records", "bigint"), ("max_bytes", "bigint"), ("max_entry_bytes", "bigint"))
_HISTORY_PG_SHAPE = (("agent_id", "text"), ("operation_id", "text"), ("bundle", "text"))


def _sqlite_sql(sql):
    return "".join(sql.replace("IF NOT EXISTS ", "").split()).rstrip(";").casefold()


def assert_sqlite_namespace(cur):
    """SQLite folds ASCII identifiers; never let TEMP/case aliases hide main."""
    if cur.execute("SELECT name FROM sqlite_temp_master WHERE name COLLATE NOCASE IN (" +
                   ",".join("?" for _ in _RESERVED) + ") LIMIT 1", _RESERVED).fetchone():
        raise EvidenceCapacityDenied("reserved evidence storage name shadowed by SQLite TEMP object")
    for row in cur.execute("SELECT name FROM main.sqlite_master WHERE type IN ('table','view') "
                           "AND name COLLATE NOCASE IN (?,?)", (TABLE, HISTORY)).fetchall():
        if row["name"] not in (TABLE, HISTORY):
            raise EvidenceCapacityDenied("noncanonical evidence table name")
    names = tuple(sql.split()[5] for sql in _sqlite_statements())
    for row in cur.execute("SELECT name FROM main.sqlite_master WHERE type='trigger' AND name COLLATE NOCASE IN (" +
                           ",".join("?" for _ in names) + ")", names).fetchall():
        if row["name"] not in names:
            raise EvidenceCapacityDenied("noncanonical evidence capacity trigger name")


def assert_postgres_namespace(cur):
    """Require one explicit durable schema; reserved TEMP objects are refused."""
    row = cur.execute("SELECT current_schema() AS schema,current_schemas(false) AS schemas").fetchone()
    if not row["schema"] or row["schemas"] != [row["schema"]]:
        raise EvidenceCapacityDenied("fixed evidence PostgreSQL namespace required")
    if cur.execute("SELECT relname FROM pg_catalog.pg_class WHERE relnamespace=pg_catalog.pg_my_temp_schema() "
                   "AND relname=ANY(%s) LIMIT 1", (list(_RESERVED),)).fetchone():
        raise EvidenceCapacityDenied("reserved evidence storage name shadowed by PostgreSQL TEMP object")
    return row["schema"]


def _read_policy(cur):
    rows = cur.execute("SELECT * FROM " + TABLE).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or type(rows[0]["singleton"]) is not int or rows[0]["singleton"] != 1 or (
            type(rows[0]["version"]) is not int or rows[0]["version"] != 1):
        raise EvidenceCapacityDenied("unsupported evidence capacity policy rows")
    EvidenceLimits(**{name: rows[0][name] for name in asdict(DEFAULTS)})
    return dict(rows[0])


def _usage(cur, *, postgres):
    size = "octet_length(bundle)" if postgres else "length(CAST(bundle AS BLOB))"
    return dict(cur.execute("SELECT count(*) AS records,coalesce(sum(" + size + "),0) AS bytes,"
                            "coalesce(max(" + size + "),0) AS largest_entry_bytes FROM " + HISTORY).fetchone())


def _sqlite_shape(cur, table, expected, ddl):
    kind = cur.execute("SELECT type,sql FROM main.sqlite_master WHERE name=?", (table,)).fetchone()
    if kind is None or kind["type"] != "table" or not isinstance(kind["sql"], str) or _sqlite_sql(kind["sql"]) != _sqlite_sql(ddl):
        raise EvidenceCapacityDenied("unsupported evidence table constraints")
    rows = cur.execute("PRAGMA main.table_xinfo(" + table + ")").fetchall()
    if tuple((r["name"], r["type"], r["pk"], r["notnull"]) for r in rows) != expected or any(
            r["hidden"] != 0 or r["dflt_value"] is not None for r in rows):
        raise EvidenceCapacityDenied("unsupported evidence table schema")
    indexes = [row for row in cur.execute("PRAGMA main.index_list(" + table + ")").fetchall() if row["unique"]]
    if table == TABLE:
        valid = not indexes
    else:
        valid = len(indexes) == 1 and indexes[0]["origin"] == "pk" and not indexes[0]["partial"]
        if valid:
            index = indexes[0]["name"].replace('"', '""')
            fields = [row for row in cur.execute('PRAGMA main.index_xinfo("' + index + '")').fetchall() if row["key"]]
            valid = [(r["name"], r["coll"], r["desc"]) for r in fields] == [
                ("agent_id", "BINARY", 0), ("operation_id", "BINARY", 0)]
    if not valid:
        raise EvidenceCapacityDenied("unsupported evidence unique key schema")


def _sqlite_metadata(cur, *, policy_exists=True):
    assert_sqlite_namespace(cur)
    if cur.execute("PRAGMA encoding").fetchone()["encoding"] != "UTF-8":
        raise EvidenceCapacityDenied("evidence capacity requires UTF-8 SQLite storage")
    _sqlite_shape(cur, HISTORY, _HISTORY_SQLITE_SHAPE, _HISTORY_DDL)
    if policy_exists:
        _sqlite_shape(cur, TABLE, _POLICY_SQLITE_SHAPE, DDL)
    if cur.execute("SELECT 1 FROM " + HISTORY + " WHERE typeof(agent_id)<>'text' OR "
                   "typeof(operation_id)<>'text' OR typeof(bundle)<>'text' LIMIT 1").fetchone():
        raise EvidenceCapacityDenied("unsupported historical evidence value types")


def _sqlite_statements():
    statements = [
        "CREATE TRIGGER IF NOT EXISTS evidence_capacity_duplicate_v1 BEFORE INSERT ON " + HISTORY +
        " WHEN EXISTS(SELECT 1 FROM " + HISTORY + " WHERE agent_id=NEW.agent_id AND operation_id=NEW.operation_id) "
        "BEGIN SELECT RAISE(ABORT,'evidence identity already exists'); END",
        "CREATE TRIGGER IF NOT EXISTS evidence_capacity_insert_v1 AFTER INSERT ON " + HISTORY + " BEGIN "
        "INSERT INTO " + TABLE + " SELECT 1,1,100000,67108864,262144 "
        "WHERE NOT EXISTS(SELECT 1 FROM " + TABLE + " WHERE singleton=1); "
        "SELECT CASE WHEN typeof(NEW.agent_id)<>'text' OR typeof(NEW.operation_id)<>'text' OR typeof(NEW.bundle)<>'text' OR "
        "(SELECT count(*) FROM " + TABLE + ")<>1 OR "
        "(SELECT typeof(singleton)<>'integer' OR singleton<>1 OR typeof(version)<>'integer' OR version<>1 OR "
        "typeof(max_records)<>'integer' OR max_records<1 OR max_records>1000000 OR "
        "typeof(max_bytes)<>'integer' OR max_bytes<1 OR max_bytes>1073741824 OR "
        "typeof(max_entry_bytes)<>'integer' OR max_entry_bytes<1 OR max_entry_bytes>1048576 OR max_entry_bytes>max_bytes "
        "FROM " + TABLE + " WHERE singleton=1) THEN RAISE(ABORT,'invalid evidence capacity policy or row') END; "
        "SELECT CASE WHEN (SELECT count(*) FROM " + HISTORY + ")>(SELECT max_records FROM " + TABLE + ") OR "
        "(SELECT coalesce(sum(length(CAST(bundle AS BLOB))),0) FROM " + HISTORY + ")>(SELECT max_bytes FROM " + TABLE + ") OR "
        "(SELECT coalesce(max(length(CAST(bundle AS BLOB))),0) FROM " + HISTORY + ")>(SELECT max_entry_bytes FROM " + TABLE + ") "
        "THEN RAISE(ABORT,'retained evidence capacity reached') END; END",
    ]
    for table, actions in ((HISTORY, ("UPDATE", "DELETE")), (TABLE, ("DELETE",))):
        for action in actions:
            name = "evidence_immutable_" + ("policy" if table == TABLE else "history") + "_" + action.lower() + "_v1"
            statements.append("CREATE TRIGGER IF NOT EXISTS " + name + " BEFORE " + action + " ON " + table +
                              " BEGIN SELECT RAISE(ABORT,'evidence history and policy cannot be removed or replaced'); END")
    statements.append("CREATE TRIGGER IF NOT EXISTS evidence_policy_no_replace_v1 BEFORE INSERT ON " + TABLE +
                      " WHEN EXISTS(SELECT 1 FROM " + TABLE + " WHERE singleton=NEW.singleton) "
                      "BEGIN SELECT RAISE(ABORT,'evidence policy already exists'); END")
    return statements


def _sqlite_installed(cur):
    for sql in _sqlite_statements():
        name = sql.split()[5]
        row = cur.execute("SELECT sql FROM main.sqlite_master WHERE type='trigger' AND name=?", (name,)).fetchone()
        if row is None or not isinstance(row["sql"], str) or _sqlite_sql(row["sql"]) != _sqlite_sql(sql):
            raise EvidenceCapacityDenied("missing or modified evidence capacity trigger")


def _sqlite_presence(cur):
    exists = cur.execute("SELECT 1 FROM main.sqlite_master WHERE name=?", (TABLE,)).fetchone() is not None
    names = tuple(sql.split()[5] for sql in _sqlite_statements())
    triggers = cur.execute("SELECT 1 FROM main.sqlite_master WHERE type='trigger' AND name COLLATE NOCASE IN (" +
                           ",".join("?" for _ in names) + ") LIMIT 1", names).fetchone() is not None
    return exists, triggers


def install_sqlite(cur):
    """Caller owns bootstrap write transaction; never materialize policy here."""
    assert_sqlite_namespace(cur)
    existed, triggers = _sqlite_presence(cur)
    _sqlite_metadata(cur, policy_exists=existed)
    if existed:
        _sqlite_installed(cur)
        _read_policy(cur)
        return
    if triggers:
        raise EvidenceCapacityDenied("evidence capacity metadata missing from installed history")
    cur.execute(DDL)
    for sql in _sqlite_statements():
        cur.execute(sql)
    _sqlite_installed(cur)


_POSTGRES_FUNCTION_SQL = {
    "agentbridge_evidence_capacity_fence_v1": """CREATE OR REPLACE FUNCTION agentbridge_evidence_capacity_fence_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'evidence capacity growth requires READ COMMITTED'; END IF; PERFORM pg_advisory_xact_lock(911001); RETURN NULL; END $$""",
    "agentbridge_evidence_duplicate_v1": """
        CREATE OR REPLACE FUNCTION agentbridge_evidence_duplicate_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE duplicate_found BOOLEAN;
        BEGIN
          IF TG_TABLE_NAME='evidence_capacity_policy_v1' THEN
            EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.evidence_capacity_policy_v1 WHERE singleton=$1)',TG_TABLE_SCHEMA) INTO duplicate_found USING NEW.singleton;
          ELSE
            EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.reconciliation_evidence WHERE agent_id=$1 AND operation_id=$2)',TG_TABLE_SCHEMA) INTO duplicate_found USING NEW.agent_id,NEW.operation_id;
          END IF;
          IF duplicate_found THEN RAISE EXCEPTION 'evidence identity or policy already exists'; END IF;
          RETURN NEW;
        END $$
    """,
    "agentbridge_evidence_capacity_v1": """
        CREATE OR REPLACE FUNCTION agentbridge_evidence_capacity_v1() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE p RECORD; n BIGINT; b BIGINT; largest BIGINT;
        BEGIN
          IF current_setting('transaction_isolation')<>'read committed' THEN
            RAISE EXCEPTION 'evidence capacity growth requires READ COMMITTED';
          END IF;
          PERFORM pg_advisory_xact_lock(911001);
          EXECUTE format('SELECT * FROM %I.evidence_capacity_policy_v1 WHERE singleton=1',TG_TABLE_SCHEMA) INTO p;
          IF p.singleton IS NULL THEN
            EXECUTE format('INSERT INTO %I.evidence_capacity_policy_v1 VALUES(1,1,100000,67108864,262144)',TG_TABLE_SCHEMA);
            EXECUTE format('SELECT * FROM %I.evidence_capacity_policy_v1 WHERE singleton=1',TG_TABLE_SCHEMA) INTO p;
          END IF;
          IF p.version<>1 OR p.max_records<1 OR p.max_records>1000000 OR p.max_bytes<1 OR p.max_bytes>1073741824 OR
             p.max_entry_bytes<1 OR p.max_entry_bytes>1048576 OR p.max_entry_bytes>p.max_bytes THEN
            RAISE EXCEPTION 'invalid evidence capacity policy';
          END IF;
          EXECUTE format('SELECT count(*),coalesce(sum(octet_length(bundle)),0),coalesce(max(octet_length(bundle)),0) FROM %I.reconciliation_evidence',TG_TABLE_SCHEMA) INTO n,b,largest;
          IF n>p.max_records OR b>p.max_bytes OR largest>p.max_entry_bytes THEN
            RAISE EXCEPTION 'retained evidence capacity reached';
          END IF;
          RETURN NULL;
        END $$
    """,
    "agentbridge_evidence_immutable_v1": """CREATE OR REPLACE FUNCTION agentbridge_evidence_immutable_v1() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'evidence history and policy cannot be removed or replaced'; END $$""",
}
_PG_TRIGGERS = {
    (TABLE, "evidence_capacity_fence_v1"): (30, "agentbridge_evidence_capacity_fence_v1", "BEFORE INSERT OR UPDATE OR DELETE", "STATEMENT"),
    (HISTORY, "evidence_capacity_fence_v1"): (30, "agentbridge_evidence_capacity_fence_v1", "BEFORE INSERT OR UPDATE OR DELETE", "STATEMENT"),
    (TABLE, "evidence_immutable_v1"): (42, "agentbridge_evidence_immutable_v1", "BEFORE DELETE OR TRUNCATE", "STATEMENT"),
    (HISTORY, "evidence_immutable_v1"): (58, "agentbridge_evidence_immutable_v1", "BEFORE UPDATE OR DELETE OR TRUNCATE", "STATEMENT"),
    (TABLE, "evidence_capacity_duplicate_v1"): (7, "agentbridge_evidence_duplicate_v1", "BEFORE INSERT", "ROW"),
    (HISTORY, "evidence_capacity_duplicate_v1"): (7, "agentbridge_evidence_duplicate_v1", "BEFORE INSERT", "ROW"),
    (HISTORY, "evidence_capacity_insert_v1"): (5, "agentbridge_evidence_capacity_v1", "AFTER INSERT", "ROW"),
}


def _postgres_shape(cur, table, expected, key):
    relation = cur.execute(
        "SELECT c.oid,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,c.relispartition,"
        "EXISTS(SELECT 1 FROM pg_catalog.pg_inherits i WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS inherits "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() AND c.relname=%s", (table,),
    ).fetchone()
    if relation is None or relation["relkind"] != "r" or relation["relpersistence"] != "p" or any(
            relation[name] for name in ("relrowsecurity", "relforcerowsecurity", "relispartition", "inherits")):
        raise EvidenceCapacityDenied("evidence storage requires ordinary permanent unfiltered PostgreSQL tables")
    rows = cur.execute(
        "SELECT column_name,data_type,is_nullable,column_default,is_identity,is_generated FROM information_schema.columns "
        "WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position", (table,),
    ).fetchall()
    if tuple((r["column_name"], r["data_type"]) for r in rows) != expected or any(
            r["is_nullable"] != "NO" or r["column_default"] is not None or r["is_identity"] != "NO" or r["is_generated"] != "NEVER" for r in rows):
        raise EvidenceCapacityDenied("unsupported evidence table schema")
    indexes = cur.execute(
        "SELECT i.indisprimary,i.indisvalid,i.indisready,i.indnatts,i.indnkeyatts,i.indpred IS NULL AS no_predicate,"
        "i.indexprs IS NULL AS no_expression,ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum,position) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY k.position) AS fields "
        "FROM pg_index i WHERE i.indrelid=%s AND i.indisunique", (relation["oid"],),
    ).fetchall()
    if len(indexes) != 1 or not all(indexes[0][name] for name in (
            "indisprimary", "indisvalid", "indisready", "no_predicate", "no_expression")) or (
            indexes[0]["indnatts"], indexes[0]["indnkeyatts"], indexes[0]["fields"]) != (len(key), len(key), list(key)):
        raise EvidenceCapacityDenied("unsupported evidence unique key schema")
    constraints = cur.execute("SELECT contype,pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                              "WHERE conrelid=%s", (relation["oid"],)).fetchall()
    if any(r["contype"] not in ("p", "c") for r in constraints):
        raise EvidenceCapacityDenied("unsupported evidence table constraints")
    checks = ["".join(r["definition"].split()).replace("(", "").replace(")", "").casefold()
              for r in constraints if r["contype"] == "c"]
    wanted = {"checksingleton=1", "checkversion=1", "checkmax_records>=1andmax_records<=1000000",
              "checkmax_bytes>=1andmax_bytes<=1073741824",
              "checkmax_entry_bytes>=1andmax_entry_bytes<=1048576andmax_entry_bytes<=max_bytes"} if table == TABLE else set()
    if len(checks) != len(wanted) or set(checks) != wanted:
        raise EvidenceCapacityDenied("unsupported evidence table constraints")


def qualified_postgres_routines(cur):
    """Read-only exact source/attribute qualification, including overload refusal."""
    names = list(_POSTGRES_FUNCTION_SQL)
    rows = cur.execute(
        "SELECT p.proname,p.prosrc,p.pronargs,p.prorettype::regtype::text AS result,p.prokind,p.prosecdef,"
        "p.provolatile,p.proleakproof,p.proisstrict,p.proparallel,p.proretset,p.provariadic,p.proconfig,l.lanname "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang "
        "WHERE n.nspname=current_schema() AND p.proname=ANY(%s)", (names,),
    ).fetchall()
    if len(rows) != len(names) or {r["proname"] for r in rows} != set(names):
        raise EvidenceCapacityDenied("missing or overloaded evidence capacity routine")
    for row in rows:
        if (row["prosrc"] != _POSTGRES_FUNCTION_SQL[row["proname"]].split("$$")[1] or row["pronargs"] != 0 or
                row["result"] != "trigger" or row["prokind"] != "f" or row["lanname"] != "plpgsql" or row["prosecdef"] or
                row["provolatile"] != "v" or row["proleakproof"] or row["proisstrict"] or row["proparallel"] != "u" or
                row["proretset"] or row["provariadic"] != 0 or row["proconfig"] != ["search_path=pg_catalog"]):
            raise EvidenceCapacityDenied("modified evidence capacity routine")
    return names


def _postgres_presence(cur):
    exists = cur.execute("SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                         "WHERE n.nspname=current_schema() AND c.relname=%s", (TABLE,)).fetchone() is not None
    functions = cur.execute("SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                            "WHERE n.nspname=current_schema() AND p.proname=ANY(%s) LIMIT 1",
                            (list(_POSTGRES_FUNCTION_SQL),)).fetchone() is not None
    triggers = cur.execute("SELECT 1 FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid "
                           "JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=current_schema() "
                           "AND t.relname=ANY(%s) AND g.tgname=ANY(%s) LIMIT 1",
                           ([TABLE, HISTORY], list({key[1] for key in _PG_TRIGGERS}))).fetchone() is not None
    return exists, functions or triggers


def _postgres_installed(cur):
    qualified_postgres_routines(cur)
    rows = cur.execute(
        "SELECT t.relname AS table_name,g.tgname,g.tgtype,g.tgenabled,g.tgattr::text AS attributes,"
        "g.tgqual IS NULL AS no_condition,g.tgargs AS arguments,g.tgnargs,g.tgisinternal,g.tgconstraint,"
        "g.tgoldtable,g.tgnewtable,p.proname AS function_name,fn.nspname AS function_schema "
        "FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "JOIN pg_proc p ON p.oid=g.tgfoid JOIN pg_namespace fn ON fn.oid=p.pronamespace "
        "WHERE n.nspname=current_schema() AND t.relname=ANY(%s) AND g.tgname=ANY(%s)",
        ([TABLE, HISTORY], list({key[1] for key in _PG_TRIGGERS})),
    ).fetchall()
    actual = {(r["table_name"], r["tgname"]): r for r in rows}
    if len(rows) != len(_PG_TRIGGERS) or set(actual) != set(_PG_TRIGGERS):
        raise EvidenceCapacityDenied("missing or unsupported evidence capacity triggers")
    schema = cur.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    for key, (kind, function, _, _) in _PG_TRIGGERS.items():
        row = actual[key]
        if (row["tgtype"] != kind or row["tgenabled"] != "O" or row["attributes"] != "" or not row["no_condition"] or
                bytes(row["arguments"]) != b"" or row["tgnargs"] != 0 or row["tgisinternal"] or row["tgconstraint"] != 0 or
                row["tgoldtable"] is not None or row["tgnewtable"] is not None or row["function_name"] != function or row["function_schema"] != schema):
            raise EvidenceCapacityDenied("modified evidence capacity trigger")


def _postgres_metadata(cur, *, policy_exists=True):
    schema = assert_postgres_namespace(cur)
    if cur.execute("SHOW server_encoding").fetchone()["server_encoding"] != "UTF8":
        raise EvidenceCapacityDenied("evidence capacity requires UTF-8 PostgreSQL storage")
    _postgres_shape(cur, HISTORY, _HISTORY_PG_SHAPE, ("agent_id", "operation_id"))
    if policy_exists:
        _postgres_shape(cur, TABLE, _POLICY_PG_SHAPE, ("singleton",))
    return schema


def install_postgres(cur):
    """Caller owns bootstrap/audit fences; no rows or partial repairs are made."""
    assert_postgres_namespace(cur)
    existed, artifacts = _postgres_presence(cur)
    _postgres_metadata(cur, policy_exists=existed)
    if existed:
        _postgres_installed(cur)
        _read_policy(cur)
        return
    if artifacts:
        raise EvidenceCapacityDenied("evidence capacity metadata missing from installed history")
    cur.execute(DDL)
    for sql in _POSTGRES_FUNCTION_SQL.values():
        cur.execute(sql)
    for (table, name), (_, function, actions, level) in _PG_TRIGGERS.items():
        cur.execute("CREATE TRIGGER " + name + " " + actions + " ON " + table + " FOR EACH " + level +
                    " EXECUTE FUNCTION " + function + "()")
    _postgres_installed(cur)


def verify_snapshot(cur, *, postgres):
    """Read-only under the caller's audit fence or offline table exclusion."""
    if postgres:
        _postgres_metadata(cur)
        _postgres_installed(cur)
    else:
        _sqlite_metadata(cur)
        _sqlite_installed(cur)
    _read_policy(cur)
    return _usage(cur, postgres=postgres)


def verify_if_installed(cur, *, postgres):
    """Untouched legacy absence is allowed; any dangling installed artifact is not."""
    if postgres:
        assert_postgres_namespace(cur)
        exists, artifacts = _postgres_presence(cur)
    else:
        assert_sqlite_namespace(cur)
        exists, artifacts = _sqlite_presence(cur)
    if exists:
        return verify_snapshot(cur, postgres=postgres)
    if artifacts:
        raise EvidenceCapacityDenied("evidence capacity metadata missing from installed history")
    return None


def policy(store, *, limits=None, audit=None):
    """Trusted library configuration, joined to the caller's existing transaction."""
    from .store import PostgresStore, SqliteStore, sql_atomic

    if not isinstance(store, (SqliteStore, PostgresStore)):
        raise EvidenceCapacityDenied("durable SQL evidence store required")
    if limits is not None and not isinstance(limits, EvidenceLimits):
        raise EvidenceCapacityDenied("EvidenceLimits required")
    postgres = isinstance(store, PostgresStore)
    with sql_atomic(store), closing(store._db.cursor()) as cur:
        if postgres:
            schema = assert_postgres_namespace(cur)
            if cur.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
                raise EvidenceCapacityDenied("evidence capacity policy requires READ COMMITTED")
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (911001,))
        verify_snapshot(cur, postgres=postgres)
        if _read_policy(cur) is None:
            cur.execute("INSERT INTO " + TABLE + " VALUES(1,1,100000,67108864,262144)")
        if limits is not None:
            marker = "%s" if postgres else "?"
            cur.execute("UPDATE " + TABLE + " SET max_records=" + marker + ",max_bytes=" + marker +
                        ",max_entry_bytes=" + marker + " WHERE singleton=1", tuple(asdict(limits).values()))
            if audit is not None:
                audit()
        if postgres and assert_postgres_namespace(cur) != schema:
            raise EvidenceCapacityDenied("evidence PostgreSQL namespace changed during configuration")
        actual = verify_snapshot(cur, postgres=postgres)
        return {**_read_policy(cur), "used_records": actual["records"], "used_bytes": actual["bytes"],
                "largest_entry_bytes": actual["largest_entry_bytes"]}
