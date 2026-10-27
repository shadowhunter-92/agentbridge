"""Explicit, fail-closed assignment of historical SQL state to one tenant.

Offline operators freeze legacy writes, make and independently restore a real
backup, verify every stored row, and only then bind the original namespace.
Historical JSON, signatures, nonces and audit hashes are never rewritten.
Rollback is allowed only before tenant-era data changes. Database owners and
filesystem administrators are trusted; these guards constrain supported old
application writers, not hostile code holding owner credentials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from .authority import _identifier
from .store import PostgresStore, SqliteStore
from .tenant_store import _install_postgres_guards, _install_sqlite_guards, _quote

_MARKER = "agentbridge_tenant_migration"
_BINDING = "tenant_store_binding"
_FREEZE = "ab_migration_freeze"


class TenantMigrationDenied(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _value(value):
    if isinstance(value, (bytes, memoryview)):
        return {"binary": base64.b64encode(value).decode()}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TenantMigrationDenied("unsupported historical SQL value; explicit migration adapter required")


def _tables(store, cur):
    if isinstance(store, SqliteStore):
        return [
            row["name"]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename")
    return [row["tablename"] for row in cur.fetchall()]


def _namespace(store):
    if isinstance(store, SqliteStore):
        name = store._db.execute("PRAGMA database_list").fetchone()["file"]
        if not name:
            raise TenantMigrationDenied("durable source and restore namespaces required")
        stat = Path(name).resolve().stat()
        return "sqlite", stat.st_dev, stat.st_ino
    row = store._db.execute(
        "SELECT inet_server_addr()::text AS addr,inet_server_port() AS port,"
        "current_database() AS db,current_schema() AS schema"
    ).fetchone()
    return "postgres", row["addr"], row["port"], row["db"], row["schema"]


def _supported_schema(store, cur):
    # Fail closed for objects outside the preserved SQL-table contract. A
    # routine/view-specific adapter must qualify its semantics before migration.
    migrated = _MARKER in _tables(store, cur)
    if isinstance(store, SqliteStore):
        if not migrated:
            triggers = cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
            if any(row["name"].startswith((_FREEZE, "tenant_guard_")) for row in triggers):
                raise TenantMigrationDenied("reserved migration objects already exist")
        databases = cur.execute("PRAGMA database_list").fetchall()
        if any(row["name"] not in ("main", "temp") for row in databases):
            raise TenantMigrationDenied("attached databases require an explicit migration adapter")
        unknown = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='view' OR "
            "(type='table' AND upper(ltrim(sql)) LIKE 'CREATE VIRTUAL TABLE%') LIMIT 1"
        ).fetchone()
    else:
        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND "
            "(c.relkind NOT IN ('r','i','S','t') OR c.relrowsecurity OR c.relforcerowsecurity "
            "OR (c.relkind='r' AND c.relpersistence<>'p')) LIMIT 1"
        )
        unknown = cur.fetchone()
        if not unknown:
            from .audit_capacity import AuditCapacityDenied, qualified_postgres_routines

            try:
                qualified = qualified_postgres_routines(cur)
            except AuditCapacityDenied as exc:
                raise TenantMigrationDenied("unsupported audit capacity migration routine") from exc
            from .checkpoint_capacity import TABLE as checkpoint_policy_table
            if checkpoint_policy_table in _tables(store, cur):
                from .checkpoint_capacity import CheckpointCapacityDenied
                from .checkpoint_capacity import qualified_postgres_routines as checkpoint_routines
                try:
                    qualified += checkpoint_routines(cur)
                except CheckpointCapacityDenied as exc:
                    raise TenantMigrationDenied("unsupported checkpoint capacity migration routine") from exc
            from .signing_journal_capacity import TABLE as signing_policy_table
            if signing_policy_table in _tables(store, cur):
                from .signing_journal_capacity import SigningJournalCapacityDenied
                from .signing_journal_capacity import qualified_postgres_routines as signing_routines

                try:
                    qualified += signing_routines(cur)
                except SigningJournalCapacityDenied as exc:
                    raise TenantMigrationDenied("unsupported signing journal capacity migration routine") from exc
            from .evidence_journal_capacity import TABLE as evidence_policy_table
            if evidence_policy_table in _tables(store, cur):
                from .evidence_journal_capacity import EvidenceCapacityDenied
                from .evidence_journal_capacity import qualified_postgres_routines as evidence_routines
                try:
                    qualified += evidence_routines(cur)
                except EvidenceCapacityDenied as exc:
                    raise TenantMigrationDenied("unsupported evidence capacity migration routine") from exc
            cur.execute(
                "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=current_schema() AND NOT (p.proname=ANY(%s)) LIMIT 1",
                (qualified + (["ab_migration_freeze", "agentbridge_tenant_write_guard"] if migrated else []),),
            )
            unknown = cur.fetchone()
        if not unknown:
            cur.execute("SELECT rulename FROM pg_rules WHERE schemaname=current_schema() LIMIT 1")
            unknown = cur.fetchone()
    if unknown:
        raise TenantMigrationDenied("unsupported schema objects require an explicit migration adapter")


def _snapshot(store, cur, *, tables=None):
    _supported_schema(store, cur)
    from .audit_capacity import AuditCapacityDenied, verify_retained_usage

    try:
        verify_retained_usage(cur, postgres=isinstance(store, PostgresStore))
    except AuditCapacityDenied as exc:
        raise TenantMigrationDenied("audit capacity counters do not preserve stored history") from exc
    from .checkpoint_capacity import CheckpointCapacityDenied, verify_if_installed
    try:
        verify_if_installed(cur, postgres=isinstance(store, PostgresStore))
    except CheckpointCapacityDenied as exc:
        raise TenantMigrationDenied("unsupported checkpoint capacity snapshot") from exc
    from .signing_journal_capacity import SigningJournalCapacityDenied
    from .signing_journal_capacity import verify_if_installed as verify_signing_capacity

    try:
        verify_signing_capacity(cur, postgres=isinstance(store, PostgresStore))
    except SigningJournalCapacityDenied as exc:
        raise TenantMigrationDenied("unsupported signing journal capacity snapshot") from exc
    from .evidence_journal_capacity import EvidenceCapacityDenied
    from .evidence_journal_capacity import verify_if_installed as verify_evidence
    try:
        verify_evidence(cur, postgres=isinstance(store, PostgresStore))
    except EvidenceCapacityDenied as exc:
        raise TenantMigrationDenied("unsupported evidence capacity snapshot") from exc
    selected = _tables(store, cur) if tables is None else tables
    manifest = {}
    for table in selected:
        if table in (_MARKER, _BINDING):
            continue
        quoted = _quote(table)
        if isinstance(store, SqliteStore):
            columns = [dict(row) for row in cur.execute("PRAGMA table_xinfo(" + quoted + ")").fetchall()]
        else:
            cur.execute(
                "SELECT column_name,data_type,is_nullable,column_default,udt_name,is_identity,identity_generation,identity_start,identity_increment,is_generated,generation_expression,collation_name "
                "FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s "
                "ORDER BY ordinal_position",
                (table,),
            )
            columns = [dict(row) for row in cur.fetchall()]
        cur.execute("SELECT * FROM " + quoted)
        rows = sorted(
            _json([_value(value) for value in row])
            if isinstance(row, tuple)
            else _json([_value(value) for value in row.values()])
            for row in (dict(row) if isinstance(store, SqliteStore) else row for row in cur.fetchall())
        )
        digest = hashlib.sha256()
        for row in rows:
            digest.update(row.encode())
            digest.update(b"\n")
        if isinstance(store, SqliteStore):
            objects = [
                dict(row)
                for row in cur.execute(
                    "SELECT type,name,sql FROM sqlite_master WHERE tbl_name=? AND sql IS NOT NULL "
                    "AND name NOT LIKE 'ab_migration_freeze%' AND name NOT LIKE 'tenant_guard_%' ORDER BY type,name",
                    (table,),
                ).fetchall()
            ]
        else:
            cur.execute(
                "SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                "WHERE conrelid=%s::regclass ORDER BY conname",
                (quoted,),
            )
            constraints = [dict(row) for row in cur.fetchall()]
            cur.execute(
                "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename=%s ORDER BY indexname",
                (table,),
            )
            indexes = [dict(row) for row in cur.fetchall()]
            cur.execute(
                "SELECT tgname,pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE tgrelid=%s::regclass "
                "AND NOT tgisinternal AND tgname NOT IN ('ab_migration_freeze','agentbridge_tenant_write_guard') ORDER BY tgname",
                (quoted,),
            )
            objects = {
                "constraints": constraints,
                "indexes": indexes,
                "triggers": [dict(row) for row in cur.fetchall()],
            }
        manifest[table] = {"columns": columns, "objects": objects, "rows": len(rows), "sha256": digest.hexdigest()}
    sequences = {}
    if isinstance(store, SqliteStore):
        if cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone():
            sequences = {
                row["name"]: row["seq"] for row in cur.execute("SELECT name,seq FROM sqlite_sequence").fetchall()
            }
    else:
        cur.execute("SELECT sequencename FROM pg_sequences WHERE schemaname=current_schema() ORDER BY sequencename")
        for name in [row["sequencename"] for row in cur.fetchall()]:
            cur.execute("SELECT last_value,is_called FROM " + _quote(name))
            sequences[name] = dict(cur.fetchone())
    return {"tables": manifest, "sequences": sequences}


class TenantMigration:
    def __init__(self, directory, legacy_store):
        if not isinstance(legacy_store, (SqliteStore, PostgresStore)) or hasattr(legacy_store, "tenant_id"):
            raise TenantMigrationDenied("explicit unassigned legacy SQL source required")
        self.directory, self.store = directory, legacy_store
        with directory.store._lock, legacy_store._lock:
            if _namespace(directory.store) == _namespace(legacy_store):
                raise TenantMigrationDenied("authority cannot be assigned as tenant data")
            self.namespace = _namespace(legacy_store)

    @contextmanager
    def _transaction(self):
        with self.store._lock:
            if isinstance(self.store, SqliteStore):
                self.store._db.execute("BEGIN IMMEDIATE")
                cur = self.store._db.cursor()
                try:
                    yield cur
                    self.store._db.execute("COMMIT")
                except BaseException:
                    self.store._db.execute("ROLLBACK")
                    raise
                finally:
                    cur.close()
            else:
                with self.store._db.transaction(), self.store._db.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
                    tables = _tables(self.store, cur)
                    if tables:
                        cur.execute(
                            "LOCK TABLE " + ",".join(_quote(table) for table in tables) + " IN ACCESS EXCLUSIVE MODE"
                        )
                    yield cur

    def _execute(self, cur, query, args=()):
        return cur.execute(query.replace("?", "%s") if isinstance(self.store, PostgresStore) else query, args)

    def _owner(self, cur, actor, tenant):
        self.directory._admin(cur, actor)
        self.directory._tenant(cur, tenant)

    def _record(self, cur):
        if _MARKER not in _tables(self.store, cur):
            raise TenantMigrationDenied("source is not frozen for tenant migration")
        row = cur.execute("SELECT record FROM " + _MARKER + " WHERE singleton=1").fetchone()
        if row is None:
            raise TenantMigrationDenied("incomplete migration marker")
        try:
            record = json.loads(row["record"])
            expected = {
                "version",
                "migration_id",
                "tenant_id",
                "phase",
                "manifest",
                "backup_sha256",
                "source_namespace",
            }
            if (
                not isinstance(record, dict)
                or set(record) != expected
                or type(record["version"]) is not int
                or record["version"] != 1
            ):
                raise ValueError("unsupported migration record")
            _identifier(record["tenant_id"], "tenant_id")
            if not isinstance(record["migration_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", record["migration_id"]):
                raise ValueError("invalid migration identity")
            if record["phase"] not in ("frozen", "backup_verified", "active"):
                raise ValueError("invalid migration phase")
            if record["source_namespace"] != list(self.namespace) or _namespace(self.store) != self.namespace:
                raise ValueError("migration source namespace changed")
            digest = record["backup_sha256"]
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ValueError("invalid backup digest")
            if record["phase"] != "frozen" and digest is None:
                raise ValueError("verified backup digest missing")
            manifest = record["manifest"]
            if not isinstance(manifest, dict) or set(manifest) != {"tables", "sequences"}:
                raise ValueError("invalid historical manifest")
            if not isinstance(manifest["tables"], dict) or not isinstance(manifest["sequences"], dict):
                raise ValueError("invalid historical manifest")
            for name, table in manifest["tables"].items():
                if name in (_MARKER, _BINDING) or name.startswith("authority_"):
                    raise ValueError("invalid historical table")
                if not isinstance(table, dict) or set(table) != {"columns", "objects", "rows", "sha256"}:
                    raise ValueError("invalid historical table manifest")
                if not isinstance(table["columns"], list) or not isinstance(table["objects"], (dict, list)):
                    raise ValueError("invalid historical table definition")
                if type(table["rows"]) is not int or table["rows"] < 0:
                    raise ValueError("invalid historical row count")
                if not isinstance(table["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", table["sha256"]):
                    raise ValueError("invalid historical row digest")
            return record
        except (TypeError, ValueError, KeyError) as exc:
            raise TenantMigrationDenied("invalid or foreign migration marker; operator recovery required") from exc

    def status(self, actor):
        """Inspect an acknowledged or lost-ACK migration without retrying it."""
        with self.directory.guard(actor), self._transaction() as cur:
            record = self._record(cur)
            with self.directory._transaction() as auth:
                self._owner(auth, actor, record["tenant_id"])
            if record["phase"] == "active":
                row = cur.execute("SELECT tenant_id,format_version FROM " + _BINDING + " WHERE singleton=1").fetchone()
                if not row or row["tenant_id"] != record["tenant_id"] or row["format_version"] != 1:
                    raise TenantMigrationDenied("active migration binding does not match its record")
            return record

    def _save(self, cur, record):
        self._execute(cur, "UPDATE " + _MARKER + " SET record=? WHERE singleton=1", (_json(record),))

    def freeze(self, actor, tenant_id):
        _identifier(tenant_id, "tenant_id")
        with self.directory.guard(actor, write=True):
            with self.directory._transaction() as auth:
                self._owner(auth, actor, tenant_id)
            with self._transaction() as cur:
                tables = _tables(self.store, cur)
                if _BINDING in tables or any(table.startswith("authority_") for table in tables):
                    raise TenantMigrationDenied("source is already assigned or contains authority state")
                if _MARKER in tables:
                    record = self._record(cur)
                    if record["tenant_id"] != tenant_id or record["manifest"] != _snapshot(self.store, cur):
                        raise TenantMigrationDenied("frozen source changed or tenant assignment conflicts")
                    return record
                manifest = _snapshot(self.store, cur)
                record = {
                    "version": 1,
                    "migration_id": uuid.uuid4().hex,
                    "tenant_id": tenant_id,
                    "phase": "frozen",
                    "manifest": manifest,
                    "backup_sha256": None,
                    "source_namespace": list(self.namespace),
                }
                cur.execute(
                    "CREATE TABLE "
                    + _MARKER
                    + " (singleton INTEGER PRIMARY KEY CHECK(singleton=1),record TEXT NOT NULL)"
                )
                self._execute(cur, "INSERT INTO " + _MARKER + " VALUES(1,?)", (_json(record),))
                if isinstance(self.store, PostgresStore):
                    cur.execute(
                        "CREATE FUNCTION " + _FREEZE + "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog "
                        "AS $$ BEGIN RAISE EXCEPTION 'legacy source frozen for tenant migration'; END $$"
                    )
                for table in tables:
                    if isinstance(self.store, SqliteStore):
                        for action in ("INSERT", "UPDATE", "DELETE"):
                            cur.execute(
                                "CREATE TRIGGER "
                                + _quote(_FREEZE + "_" + uuid.uuid5(uuid.NAMESPACE_OID, table + action).hex)
                                + " BEFORE "
                                + action
                                + " ON "
                                + _quote(table)
                                + " BEGIN SELECT RAISE(ABORT,'legacy source frozen for tenant migration'); END"
                            )
                    else:
                        cur.execute(
                            "CREATE TRIGGER "
                            + _FREEZE
                            + " BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON "
                            + _quote(table)
                            + " FOR EACH STATEMENT EXECUTE FUNCTION "
                            + _FREEZE
                            + "()"
                        )
                return record

    def _backup_record(self, restored, read, record):
        tables = _tables(restored, read)
        if _MARKER not in tables or _BINDING in tables:
            raise TenantMigrationDenied("restore is not an unactivated frozen migration backup")
        row = read.execute("SELECT record FROM " + _MARKER + " WHERE singleton=1").fetchone()
        expected = {**record, "phase": "frozen", "backup_sha256": None}
        try:
            actual = json.loads(row["record"]) if row else None
        except (TypeError, ValueError) as exc:
            raise TenantMigrationDenied("restored migration metadata is invalid") from exc
        if actual != expected:
            raise TenantMigrationDenied("restored migration metadata differs from the frozen source")

    def _verified(self, cur, record, restored, archive):
        if record["manifest"] != _snapshot(self.store, cur):
            raise TenantMigrationDenied("historical state changed after freeze")
        if type(self.store) is not type(restored):
            raise TenantMigrationDenied("same-backend independently restored backup required")
        with restored._lock:
            if _namespace(restored) == self.namespace:
                raise TenantMigrationDenied("backup restore must be an independent namespace")
            if isinstance(restored, SqliteStore):
                read = restored._db.cursor()
                try:
                    self._backup_record(restored, read, record)
                    manifest = _snapshot(restored, read)
                finally:
                    read.close()
            else:
                with restored._db.transaction(), restored._db.cursor() as read:
                    self._backup_record(restored, read, record)
                    manifest = _snapshot(restored, read)
        if manifest != record["manifest"]:
            raise TenantMigrationDenied("restored backup does not preserve all historical rows")
        with Path(archive).open("rb") as backup:
            digest = hashlib.file_digest(backup, "sha256").hexdigest()
        if record["backup_sha256"] not in (None, digest):
            raise TenantMigrationDenied("verified backup archive changed")
        return digest

    def verify_backup(self, actor, restored, archive):
        with self.directory.guard(actor, write=True), self._transaction() as cur:
            record = self._record(cur)
            with self.directory._transaction() as auth:
                self._owner(auth, actor, record["tenant_id"])
            if record["phase"] not in ("frozen", "backup_verified"):
                raise TenantMigrationDenied("backup verification is not valid in this migration phase")
            record["backup_sha256"] = self._verified(cur, record, restored, archive)
            record["phase"] = "backup_verified"
            self._save(cur, record)
            return record

    def _drop_guards(self, cur, tables, *, tenant=False):
        if isinstance(self.store, SqliteStore):
            prefixes = (_FREEZE, "tenant_guard_") if tenant else (_FREEZE,)
            triggers = cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
            for trigger in triggers:
                if trigger["name"].startswith(prefixes):
                    cur.execute("DROP TRIGGER " + _quote(trigger["name"]))
        else:
            for table in tables:
                cur.execute("DROP TRIGGER IF EXISTS " + _FREEZE + " ON " + _quote(table))
                if tenant:
                    cur.execute("DROP TRIGGER IF EXISTS agentbridge_tenant_write_guard ON " + _quote(table))
            cur.execute("DROP FUNCTION IF EXISTS " + _FREEZE + "()")
            if tenant:
                cur.execute("DROP FUNCTION IF EXISTS agentbridge_tenant_write_guard()")

    def activate(self, actor, restored, archive, *, checkpoint=None):
        with self.directory.guard(actor, write=True), self._transaction() as cur:
            record = self._record(cur)
            with self.directory._transaction() as auth:
                self._owner(auth, actor, record["tenant_id"])
            if record["phase"] != "backup_verified":
                raise TenantMigrationDenied("verified backup/restore is required before activation")
            self._verified(cur, record, restored, archive)
            cur.execute(
                "CREATE TABLE " + _BINDING + " (singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                "tenant_id TEXT NOT NULL,store_id TEXT NOT NULL,format_version INTEGER NOT NULL)"
            )
            self._execute(cur, "INSERT INTO " + _BINDING + " VALUES(1,?,?,1)", (record["tenant_id"], uuid.uuid4().hex))
            if checkpoint is not None:
                checkpoint("binding_created")
            record["phase"] = "active"
            self._save(cur, record)
            tables = _tables(self.store, cur)
            self._drop_guards(cur, tables)
            if isinstance(self.store, SqliteStore):
                _install_sqlite_guards(cur, tables)
            else:
                schema = cur.execute("SELECT current_schema() AS schema").fetchone()["schema"]
                _install_postgres_guards(cur, schema, tables)
            if checkpoint is not None:
                checkpoint("guards_installed")
            return record

    def rollback(self, actor, *, checkpoint=None):
        with self.directory.guard(actor, write=True), self._transaction() as cur:
            record = self._record(cur)
            with self.directory._transaction() as auth:
                self._owner(auth, actor, record["tenant_id"])
            tables = _tables(self.store, cur)
            # No restore-over-live shortcut: tenant-era writes, even terminal or
            # apparently harmless writes, make this structural rollback unsafe.
            if record["manifest"] != _snapshot(self.store, cur, tables=record["manifest"]["tables"]):
                raise TenantMigrationDenied("tenant-era state changed; forward recovery required")
            extra = set(tables) - set(record["manifest"]["tables"]) - {_MARKER, _BINDING}
            for table in extra:
                if cur.execute("SELECT 1 FROM " + _quote(table) + " LIMIT 1").fetchone():
                    raise TenantMigrationDenied("tenant-era state exists; forward recovery required")
            self._drop_guards(cur, tables, tenant=True)
            for table in sorted(extra):
                cur.execute("DROP TABLE " + _quote(table))
            if _BINDING in tables:
                cur.execute("DROP TABLE " + _BINDING)
            cur.execute("DROP TABLE " + _MARKER)
            if checkpoint is not None:
                checkpoint("rollback_prepared")
            return {
                "tenant_id": record["tenant_id"],
                "rolled_back": True,
                "backup_sha256": record["backup_sha256"],
                "historical_rows_preserved": True,
            }
