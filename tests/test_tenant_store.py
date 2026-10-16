"""Database-enforced namespace separation and old/new connection compatibility."""
import os
import secrets
import uuid

import pytest

from src.governance.identity import AgentIdentity
from src.governance.store import PostgresStore, SqliteStore
from src.governance.tenant_store import (
    TenantPostgresStore,
    TenantSqliteStore,
    TenantStoreDenied,
    TenantStoreRegistry,
)
from tests.test_authority import agent_request, enrolled
from tests.test_authority import authority as authority


@pytest.fixture
def namespaces(authority, tmp_path):
    directory = authority[0]
    handles = []
    if isinstance(directory.store, SqliteStore):
        def factory(tenant, *, legacy=False):
            path = tmp_path / (tenant + '.sqlite')
            store = SqliteStore(str(path)) if legacy else TenantSqliteStore(str(path), tenant_id=tenant)
            handles.append(store)
            return store
        yield factory
        for store in handles:
            store.close()
    else:
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        assigned = {}
        with psycopg.connect(os.environ['AGENTBRIDGE_TEST_PG'], autocommit=True) as admin:
            db = admin.info.dbname
            admin.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db)))
            def factory(tenant, *, legacy=False):
                if tenant not in assigned:
                    role = 'ab_role_' + uuid.uuid4().hex
                    schema = 'ab_tenant_' + uuid.uuid4().hex
                    password = secrets.token_hex(24)
                    admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
                    admin.execute(sql.SQL('CREATE SCHEMA {} AUTHORIZATION {}').format(sql.Identifier(schema), sql.Identifier(role)))
                    assigned[tenant] = (role, schema, make_conninfo(os.environ['AGENTBRIDGE_TEST_PG'], user=role, password=password))
                role, schema, dsn = assigned[tenant]
                store = PostgresStore(make_conninfo(dsn, options='-csearch_path='+schema)) if legacy else TenantPostgresStore(dsn, schema=schema, tenant_id=tenant)
                handles.append(store)
                return store
            try:
                yield factory
            finally:
                for store in handles:
                    store.close()
                for role, schema, _ in assigned.values():
                    admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
                    admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
                admin.execute(sql.SQL('GRANT TEMP ON DATABASE {} TO PUBLIC').format(sql.Identifier(db)))


def test_same_ids_have_separate_data_and_registry_rejects_scope_override(authority, namespaces):
    directory, owner, _, _, _ = authority
    a, b = namespaces('alpha'), namespaces('beta')
    a.upsert_identity('shared-id', AgentIdentity.generate('shared-id').public_key_hex)
    b.upsert_identity('shared-id', AgentIdentity.generate('shared-id').public_key_hex)
    a.upsert_budget('shared-id', {'spent':1})
    b.upsert_budget('shared-id', {'spent':9})
    assert a.get_identity('shared-id') != b.get_identity('shared-id')
    registry = TenantStoreRegistry(directory, {'alpha':a, 'beta':b})
    identity = enrolled(directory, owner)
    principal = agent_request(directory, identity=identity)
    assert registry.resolve(principal).get_budget('shared-id')['spent'] == 1
    with pytest.raises(TenantStoreDenied):
        registry.resolve(principal, tenant_id='beta')
    assert registry.resolve(owner, tenant_id='beta').get_budget('shared-id')['spent'] == 9


def test_scope_binding_is_immutable_and_wrong_binding_is_rejected(authority, namespaces):
    directory, _, _, _, _ = authority
    a = namespaces('alpha')
    with pytest.raises(TenantStoreDenied):
        TenantStoreRegistry(directory, {'beta':a})
    with pytest.raises(Exception, match='tenant write scope required'):
        if isinstance(a, SqliteStore):
            a._db.execute("UPDATE tenant_store_binding SET tenant_id='beta'")
        else:
            a._db.execute("UPDATE tenant_store_binding SET tenant_id='beta'")
    a.assert_scope()


def test_unassigned_populated_legacy_storage_never_auto_activates(authority, namespaces):
    old = namespaces('alpha', legacy=True)
    old.upsert_budget('legacy-agent', {'spent':3,'reserved':7,'pending':{'unknown-operation':7}})
    before = old.get_budget('legacy-agent')
    with pytest.raises(TenantStoreDenied, match='legacy rows'):
        namespaces('alpha')
    assert old.get_budget('legacy-agent') == before


def test_old_connection_can_read_legacy_bytes_but_cannot_write_after_binding(authority, namespaces):
    scoped = namespaces('alpha')
    scoped.upsert_budget('worker', {'spent':1,'pending':{}})
    legacy = namespaces('alpha', legacy=True)
    assert legacy.get_budget('worker') == scoped.get_budget('worker')
    with pytest.raises(Exception, match='agentbridge_current_tenant|tenant write scope required'):
        legacy.upsert_budget('worker', {'spent':999})
    assert scoped.get_budget('worker')['spent'] == 1


def test_restart_preserves_binding_and_helpers_can_guard_new_tables(authority, namespaces):
    first = namespaces('alpha')
    first.upsert_budget('worker', {'spent':2})
    second = namespaces('alpha')
    assert first.store_id == second.store_id
    from src.governance.operation_ledger import OperationLedger
    ledger = OperationLedger(second)
    second.seal_writes()
    ledger.claim('worker','same-operation','fingerprint')
    legacy = namespaces('alpha', legacy=True)
    assert OperationLedger(legacy).get('worker','same-operation')['state'] == 'unknown'
    with pytest.raises(Exception, match='agentbridge_current_tenant|tenant write scope required'):
        OperationLedger(legacy).claim('worker','other-operation','fingerprint')


def test_postgres_tenant_role_cannot_read_other_namespace(authority, namespaces):
    if isinstance(authority[0].store, SqliteStore):
        pytest.skip('PostgreSQL server privilege boundary')
    import psycopg
    from psycopg import sql
    a, b = namespaces('alpha'), namespaces('beta')
    a.upsert_budget('worker', {'spent':1})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        b._db.execute(sql.SQL('SELECT * FROM {}.budgets').format(sql.Identifier(a.schema)))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        b._db.execute('CREATE TEMP TABLE shadow_budget(id integer)')
    # Resetting the session selector cannot turn beta's physical namespace into
    # alpha, and assert_scope detects accidental scope drift before use.
    b._db.execute("SELECT set_config('agentbridge.tenant_id','alpha',false)")
    with pytest.raises(TenantStoreDenied):
        b.assert_scope()
