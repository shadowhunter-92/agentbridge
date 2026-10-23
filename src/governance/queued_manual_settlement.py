"""Current operator authority for private, same-store task reconciliation."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType

from .authority import AuthorityDenied, _Cursor
from .store import PostgresStore, SqliteStore, sql_atomic

_IDENTITY = "SELECT current_database() AS db,inet_server_addr()::text AS addr,inet_server_port() AS port"
_CONFIGURATION = _IDENTITY + ",current_schema() AS schema,current_user AS role,session_user AS session,current_setting('search_path') AS search_path"


@dataclass(frozen=True, slots=True)
class _AuthorityReader:
    store: object = field(repr=False)
    parameters: object = field(repr=False)
    identity: object


def capture_authority_reader(directory):
    """Pin actual callback/session-selected namespace at kernel setup.

    This runs before any tenant settlement fence. Connection parameters and the
    password remain private process configuration and never enter durable rows.
    """
    if not isinstance(directory.store, PostgresStore):
        return None
    with directory.store._lock:
        identity = dict(directory.store._db.execute(_CONFIGURATION).fetchone())
        schema = identity["schema"]
        if not isinstance(schema, str) or not schema or schema.startswith("pg_"):
            raise AuthorityDenied("qualified durable authority namespace required")
        configured = directory.store._db.info.get_parameters()
        password = directory.store._db.pgconn.password
        if password:
            configured["password"] = password.decode()
    configured["options"] = configured.get("options", "") + " -cstatement_timeout=2000 -clock_timeout=1000"
    configured["connect_timeout"] = 3
    return _AuthorityReader(directory.store, MappingProxyType(configured), MappingProxyType(identity))


def assert_authority_reader_configuration(kernel):
    """Called inside the entry directory guard, before a tenant fence exists."""
    reader = kernel._queued_authority_reader
    if reader is None:
        return
    if reader.store is not kernel.directory.store or \
            dict(reader.identity) != dict(kernel.directory.store._db.execute(_CONFIGURATION).fetchone()):
        raise AuthorityDenied("queued authority namespace/configuration changed; rebuild the configured kernel")


def _session(kernel, runtime, session):
    from .tenant_kernel import TenantSession
    if not isinstance(session, TenantSession) or session.kernel is not kernel or \
            session.tenant_id != runtime.store.tenant_id or kernel._runtimes.get(session.tenant_id) is not runtime or \
            kernel.storage._stores.get(session.tenant_id) is not runtime.store:
        raise AuthorityDenied("exact current operator settlement session required")
    if session.principal.kind != "platform_admin" and session.principal.tenant_id != runtime.store.tenant_id:
        raise AuthorityDenied("operator principal and resource tenant must match")
    session._require_permission("budgets:write")


def _independent_authority_current(directory, tenant_store, principal, reader):
    """The tenant connection already owns the shared authority fence.

    Reuse the trusted authority connection's parameters and exact namespace on a
    bounded raw read connection. Do not bootstrap, acquire a second advisory
    lock, or wait on the directory's Python mutex: a local writer may own that
    mutex while waiting for the tenant-held exclusive/shared fence.
    """
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    if not isinstance(reader, _AuthorityReader) or reader.store is not directory.store:
        raise AuthorityDenied("kernel-pinned authority reader required")
    with psycopg.connect(**reader.parameters, autocommit=True, row_factory=dict_row) as connection:
        authority_identity = connection.execute(_IDENTITY).fetchone()
        tenant_identity = tenant_store._db.execute(_IDENTITY).fetchone()
        if dict(authority_identity) != dict(tenant_identity) or any(authority_identity[name] != reader.identity[name]
                for name in ("db", "addr", "port")) or authority_identity["addr"] is None or authority_identity["port"] is None:
            raise AuthorityDenied("manual settlement requires the same qualified PostgreSQL endpoint and database")
        with connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY")
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(reader.identity["role"])))
            connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(reader.identity["schema"])))
            actual = connection.execute(_CONFIGURATION).fetchone()
            if any(actual[name] != reader.identity[name] for name in ("schema", "role", "session")):
                raise AuthorityDenied("raw authority read namespace/role does not match configured directory")
            with connection.cursor() as raw:
                cursor = _Cursor(raw, True)
                directory._current(cursor, principal)
                directory._tenant(cursor, tenant_store.tenant_id)


@contextmanager
def settlement_atomic(kernel, runtime, operator_session=None):
    """Automatic readback composes; new manual review owns its actual commit."""
    if operator_session is None:
        with sql_atomic(runtime.store):
            yield
        return
    _session(kernel, runtime, operator_session)
    directory, principal, store = kernel.directory, operator_session.principal, runtime.store
    # An outer caller could retain its transaction beyond both authority expiry
    # and our savepoint. Manual attribution therefore requires the actual commit.
    from .queued_task_dispatch import _idle
    _idle(runtime)
    if isinstance(store, SqliteStore) and isinstance(directory.store, SqliteStore):
        # Existing authority-before-tenant order. SQLite has no second 911005
        # advisory acquire; current trust is read on the owned tenant connection.
        with directory.guard(principal):
            _session(kernel, runtime, operator_session)
            if kernel.storage.resolve(principal, tenant_id=store.tenant_id) is not store:
                raise AuthorityDenied("operator resource tenant unavailable")
            with sql_atomic(store):
                yield
                directory._verify_seal(principal)
        return
    if not isinstance(store, PostgresStore) or not isinstance(directory.store, PostgresStore):
        raise AuthorityDenied("unsupported mixed-backend manual settlement")
    with sql_atomic(store):
        # One held shared fence protects current authority through the tenant
        # COMMIT. All trust/operation/budget/lifecycle/audit locks follow it.
        store._db.execute("SELECT pg_advisory_xact_lock_shared(%s)", (911005,))
        _independent_authority_current(directory, store, principal, kernel._queued_authority_reader)
        _session(kernel, runtime, operator_session)
        yield
        directory._verify_seal(principal)
