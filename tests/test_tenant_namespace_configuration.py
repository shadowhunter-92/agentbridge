"""Reject operator misconfiguration before it weakens a tenant SQL boundary."""

import os

import pytest

from src.governance.authority import AuthorityDirectory
from src.governance.store import SqliteStore
from src.governance.tenant_store import TenantStoreDenied, TenantStoreRegistry
from tests.test_authority import authority as authority
from tests.test_tenant_store import namespaces as namespaces


def test_authority_cannot_use_ephemeral_or_tenant_namespace(authority, namespaces):
    directory = authority[0]
    scoped = namespaces("alpha")
    with pytest.raises(ValueError, match="tenant data namespace"):
        AuthorityDirectory(scoped, verifiers=directory.verifiers)


def test_authority_rejects_in_memory_namespace(authority):
    memory = SqliteStore(":memory:")
    try:
        with pytest.raises(ValueError, match="durable, separate"):
            AuthorityDirectory(memory, verifiers=authority[0].verifiers)
    finally:
        memory.close()


def _postgres(authority):
    if isinstance(authority[0].store, SqliteStore):
        pytest.skip("PostgreSQL server privilege boundary")


def test_registry_rejects_cross_namespace_usage_grant(authority, namespaces):
    _postgres(authority)
    import psycopg
    from psycopg import sql

    a, b = namespaces("alpha"), namespaces("beta")
    with psycopg.connect(os.environ["AGENTBRIDGE_TEST_PG"], autocommit=True) as admin:
        admin.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(b.schema), sql.Identifier(a._role))
        )
        try:
            with pytest.raises(TenantStoreDenied, match="another tenant or authority"):
                TenantStoreRegistry(authority[0], {"alpha": a, "beta": b})
        finally:
            admin.execute(
                sql.SQL("REVOKE USAGE ON SCHEMA {} FROM {}").format(sql.Identifier(b.schema), sql.Identifier(a._role))
            )
    TenantStoreRegistry(authority[0], {"alpha": a, "beta": b})


def test_registry_rejects_authority_schema_usage_grant(authority, namespaces):
    _postgres(authority)
    import psycopg
    from psycopg import sql

    a = namespaces("alpha")
    schema = authority[0].store._db.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    with psycopg.connect(os.environ["AGENTBRIDGE_TEST_PG"], autocommit=True) as admin:
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(a._role)))
        try:
            with pytest.raises(TenantStoreDenied, match="another tenant or authority"):
                TenantStoreRegistry(authority[0], {"alpha": a})
        finally:
            admin.execute(
                sql.SQL("REVOKE USAGE ON SCHEMA {} FROM {}").format(sql.Identifier(schema), sql.Identifier(a._role))
            )


def test_tenant_login_cannot_inherit_another_role(authority, namespaces):
    _postgres(authority)
    import psycopg
    from psycopg import sql

    a, b = namespaces("alpha"), namespaces("beta")
    with psycopg.connect(os.environ["AGENTBRIDGE_TEST_PG"], autocommit=True) as admin:
        admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(b._role), sql.Identifier(a._role)))
        try:
            with pytest.raises(TenantStoreDenied, match="dedicated unprivileged"):
                namespaces("alpha")
        finally:
            admin.execute(sql.SQL("REVOKE {} FROM {}").format(sql.Identifier(b._role), sql.Identifier(a._role)))


def test_scope_rejects_additional_search_path_namespace(authority, namespaces):
    _postgres(authority)
    a = namespaces("alpha")
    a._db.execute("SELECT set_config('search_path', %s, false)", (a.schema + ",public",))
    with pytest.raises(TenantStoreDenied, match="session scope changed"):
        a.assert_scope()
