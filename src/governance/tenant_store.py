"""Explicit tenant SQL namespaces with durable binding and legacy write guards.

One tenant owns a SQLite file or a PostgreSQL schema/role. Existing governance
classes and evidence formats operate unchanged within that namespace. Trusted
operator configuration supplies namespaces; request tenant fields do not.
Populated unassigned legacy state is rejected until a verified migration binds it.
"""

from __future__ import annotations

import pathlib
import re
import uuid

from .authority import AuthorityDenied, _identifier
from .store import PostgresStore, SqliteStore


class TenantStoreDenied(AuthorityDenied):
    """Namespace is unassigned, shared, privileged or bound to another tenant."""


def _quote(value):
    return '"' + value.replace('"', '""') + '"'


def _install_sqlite_guards(cur, tables):
    for table in tables:
        for action in ("INSERT", "UPDATE", "DELETE"):
            name = "tenant_guard_" + uuid.uuid5(uuid.NAMESPACE_OID, table + ":" + action).hex
            condition = (
                "1"
                if table == "tenant_store_binding" and action != "INSERT"
                else "agentbridge_current_tenant() IS NOT (SELECT tenant_id FROM tenant_store_binding WHERE singleton=1)"
            )
            cur.execute(
                "CREATE TRIGGER IF NOT EXISTS "
                + _quote(name)
                + " BEFORE "
                + action
                + " ON "
                + _quote(table)
                + " WHEN "
                + condition
                + " BEGIN SELECT RAISE(ABORT,'tenant write scope required'); END"
            )


def _install_postgres_guards(cur, schema, tables):
    function = _quote(schema) + ".agentbridge_tenant_write_guard"
    binding = _quote(schema) + ".tenant_store_binding"
    cur.execute(
        "CREATE OR REPLACE FUNCTION "
        + function
        + "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN IF (TG_TABLE_NAME='tenant_store_binding' AND TG_OP<>'INSERT') OR current_setting('agentbridge.tenant_id',true) IS DISTINCT FROM (SELECT tenant_id FROM "
        + binding
        + " WHERE singleton=1) THEN RAISE EXCEPTION 'tenant write scope required'; END IF; RETURN NULL; END $$"
    )
    for table in tables:
        name = _quote("agentbridge_tenant_write_guard")
        target = _quote(schema) + "." + _quote(table)
        cur.execute("DROP TRIGGER IF EXISTS " + name + " ON " + target)
        # Statement-level guard returning NULL does not suppress rows.
        cur.execute(
            "CREATE TRIGGER "
            + name
            + " BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON "
            + target
            + " FOR EACH STATEMENT EXECUTE FUNCTION "
            + function
            + "()"
        )


class TenantSqliteStore(SqliteStore):
    def __init__(self, path, *, tenant_id):
        _identifier(tenant_id, "tenant_id")
        self.tenant_id = tenant_id
        super().__init__(path)
        try:
            filename = self._db.execute("PRAGMA database_list").fetchone()["file"]
            if not filename:
                raise TenantStoreDenied("tenant storage requires a durable private SQLite file")
            self.path = pathlib.Path(filename).resolve()
            stat = self.path.stat()
            self.namespace_key = ("sqlite", stat.st_dev, stat.st_ino)
            self._db.create_function("agentbridge_current_tenant", 0, lambda: self.tenant_id, deterministic=True)
            self._initialize_scope()
        except BaseException:
            self.close()
            raise

    def _tables(self):
        return [
            r["name"]
            for r in self._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]

    def _initialize_scope(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                tables = self._tables()
                if "tenant_store_binding" not in tables:
                    if any(
                        self._db.execute("SELECT 1 FROM " + _quote(table) + " LIMIT 1").fetchone() for table in tables
                    ):
                        raise TenantStoreDenied("unassigned legacy rows require verified backup and explicit migration")
                    self._db.execute(
                        "CREATE TABLE tenant_store_binding (singleton INTEGER PRIMARY KEY CHECK(singleton=1), tenant_id TEXT NOT NULL, store_id TEXT NOT NULL, format_version INTEGER NOT NULL)"
                    )
                    self._db.execute(
                        "INSERT INTO tenant_store_binding VALUES(1,?,?,1)", (self.tenant_id, uuid.uuid4().hex)
                    )
                row = self._db.execute("SELECT * FROM tenant_store_binding WHERE singleton=1").fetchone()
                if not row or row["tenant_id"] != self.tenant_id or row["format_version"] != 1:
                    raise TenantStoreDenied("SQLite namespace is bound to different or unsupported authority")
                self.store_id = row["store_id"]
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        self.seal_writes()

    def assert_scope(self):
        with self._lock:
            row = self._db.execute(
                "SELECT tenant_id,store_id,format_version FROM tenant_store_binding WHERE singleton=1"
            ).fetchone()
            if (
                not row
                or row["tenant_id"] != self.tenant_id
                or row["store_id"] != self.store_id
                or row["format_version"] != 1
            ):
                raise TenantStoreDenied("tenant storage binding changed")

    def seal_writes(self):
        """Guard all current tables, including tables created by kernel helpers.

        A legacy connection has no agentbridge_current_tenant function and fails
        on writes instead of silently running an old authorization model.
        """
        with self._lock:
            self.assert_scope()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                _install_sqlite_guards(self._db, self._tables())
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise


class TenantPostgresStore(PostgresStore):
    def __init__(self, dsn, *, schema, tenant_id):
        from psycopg.conninfo import make_conninfo

        _identifier(tenant_id, "tenant_id")
        if (
            not isinstance(schema, str)
            or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema)
            or schema == "public"
            or schema.startswith("pg_")
        ):
            raise TenantStoreDenied("operator-provisioned private PostgreSQL schema required")
        self.tenant_id, self.schema = tenant_id, schema
        # pg_catalog remains implicit before the one explicitly trusted schema.
        # Never fall back to public or a request-selected namespace.
        super().__init__(
            make_conninfo(dsn, options="-csearch_path=" + schema), initialize_connection=self._prepare_connection
        )
        try:
            self._initialize_scope()
        except BaseException:
            self.close()
            raise

    def _prepare_connection(self, connection):
        # Validate BEFORE inherited schema bootstrap can create any objects.
        with connection.cursor() as cur:
            cur.execute(
                "SELECT current_database() AS db,current_schema() AS schema,current_user AS role,session_user AS session,inet_server_addr()::text AS addr,inet_server_port() AS port"
            )
            identity = cur.fetchone()
            cur.execute(
                "SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
            privileges = cur.fetchone()
            cur.execute(
                "SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user) LIMIT 1"
            )
            inherited_role = cur.fetchone() is not None
            cur.execute(
                "SELECT has_database_privilege(current_user,current_database(),'TEMP') AS temp, pg_get_userbyid(datdba)=current_user AS owner FROM pg_database WHERE datname=current_database()"
            )
            database = cur.fetchone()
            cur.execute("SELECT current_schemas(false) AS schemas")
            path = cur.fetchone()["schemas"]
            if (
                identity["schema"] != self.schema
                or path != [self.schema]
                or identity["role"] != identity["session"]
                or any(privileges.values())
                or inherited_role
                or database["temp"]
                or database["owner"]
            ):
                raise TenantStoreDenied("dedicated unprivileged tenant login and private search path required")
            self.namespace_key = ("postgres", identity["addr"], identity["port"], identity["db"], self.schema)
            self._role = identity["role"]
            cur.execute("SELECT set_config('agentbridge.tenant_id',%s,false)", (self.tenant_id,))

    def _tables(self, cur):
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (self.schema,))
        return [row["tablename"] for row in cur.fetchall()]

    def _initialize_scope(self):
        with self._lock, self._db.transaction(), self._db.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
            tables = self._tables(cur)
            if "tenant_store_binding" not in tables:
                for table in tables:
                    cur.execute("SELECT 1 FROM " + _quote(self.schema) + "." + _quote(table) + " LIMIT 1")
                    if cur.fetchone():
                        raise TenantStoreDenied("unassigned legacy rows require verified backup and explicit migration")
                cur.execute(
                    "CREATE TABLE tenant_store_binding (singleton INTEGER PRIMARY KEY CHECK(singleton=1),tenant_id TEXT NOT NULL,store_id TEXT NOT NULL,format_version INTEGER NOT NULL)"
                )
                cur.execute("INSERT INTO tenant_store_binding VALUES(1,%s,%s,1)", (self.tenant_id, uuid.uuid4().hex))
            cur.execute("SELECT * FROM tenant_store_binding WHERE singleton=1")
            row = cur.fetchone()
            if not row or row["tenant_id"] != self.tenant_id or row["format_version"] != 1:
                raise TenantStoreDenied("PostgreSQL namespace is bound to different or unsupported authority")
            self.store_id = row["store_id"]
        self.seal_writes()

    def assert_scope(self):
        with self._lock, self._db.cursor() as cur:
            cur.execute(
                "SELECT tenant_id,store_id,format_version,current_schema() AS schema,current_setting('agentbridge.tenant_id',true) AS session_tenant,current_user AS role,current_schemas(false) AS schemas FROM "
                + _quote(self.schema)
                + ".tenant_store_binding WHERE singleton=1"
            )
            row = cur.fetchone()
            if (
                not row
                or row["tenant_id"] != self.tenant_id
                or row["store_id"] != self.store_id
                or row["format_version"] != 1
                or row["schema"] != self.schema
                or row["session_tenant"] != self.tenant_id
                or row["role"] != self._role
                or row["schemas"] != [self.schema]
            ):
                raise TenantStoreDenied("tenant storage binding or session scope changed")

    def seal_writes(self):
        with self._lock, self._db.transaction(), self._db.cursor() as cur:
            self.assert_scope()
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
            _install_postgres_guards(cur, self.schema, self._tables(cur))


class TenantStoreRegistry:
    """Trusted namespace map; selects storage only for current sealed principals."""

    def __init__(self, directory, stores):
        self.directory, self._stores = directory, dict(stores)
        namespaces = set()
        store_ids = set()
        for tenant, store in self._stores.items():
            if not isinstance(store, (TenantSqliteStore, TenantPostgresStore)) or store.tenant_id != tenant:
                raise TenantStoreDenied("every configured namespace must have an exact tenant binding")
            store.assert_scope()
            if store.namespace_key in namespaces or store.store_id in store_ids:
                raise TenantStoreDenied("tenant namespaces must not share physical or restored storage")
            namespaces.add(store.namespace_key)
            store_ids.add(store.store_id)
        self._validate_separation()

    def _validate_separation(self):
        source = self.directory.store
        if isinstance(source, SqliteStore):
            with source._lock:
                filename = source._db.execute("PRAGMA database_list").fetchone()["file"]
            stat = pathlib.Path(filename).resolve().stat()
            authority_namespace = ("sqlite", stat.st_dev, stat.st_ino)
        else:
            with source._lock, source._db.cursor() as cur:
                cur.execute(
                    "SELECT inet_server_addr()::text AS addr,inet_server_port() AS port,current_database() AS db,current_schema() AS schema"
                )
                row = cur.fetchone()
            authority_namespace = ("postgres", row["addr"], row["port"], row["db"], row["schema"])
        for store in self._stores.values():
            if store.namespace_key == authority_namespace:
                raise TenantStoreDenied("authority and tenant data must not share a namespace")
            if not isinstance(store, TenantPostgresStore):
                continue
            other_schemas = [
                other.schema
                for other in self._stores.values()
                if isinstance(other, TenantPostgresStore)
                and other is not store
                and other.namespace_key[:4] == store.namespace_key[:4]
            ]
            if authority_namespace[:4] == store.namespace_key[:4]:
                other_schemas.append(authority_namespace[4])
            with store._lock, store._db.cursor() as cur:
                cur.execute(
                    "SELECT nspname FROM pg_namespace WHERE nspname=ANY(%s) AND has_schema_privilege(current_user,oid,'USAGE')",
                    (other_schemas,),
                )
                if cur.fetchone():
                    raise TenantStoreDenied("tenant SQL role can access another tenant or authority namespace")

    def resolve(self, principal, *, tenant_id=None):
        self.directory.assert_current(principal)
        if principal.kind == "platform_admin":
            selected = _identifier(tenant_id, "explicit platform target tenant")
            with self.directory._transaction() as cur:
                self.directory._tenant(cur, selected)
        else:
            selected = principal.tenant_id
            if tenant_id is not None and tenant_id != selected:
                raise TenantStoreDenied("authenticated tenant conflicts with requested resource scope")
        store = self._stores.get(selected)
        if store is None:
            raise TenantStoreDenied("tenant storage is not explicitly configured")
        store.assert_scope()
        return store

    def describe(self, principal):
        with self.directory._transaction() as cur:
            self.directory._admin(cur, principal)
        return [
            {"tenant_id": tenant, "store_id": store.store_id, "backend": store.namespace_key[0]}
            for tenant, store in sorted(self._stores.items())
        ]
