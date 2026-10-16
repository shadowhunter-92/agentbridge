"""Real PostgreSQL grant checks must not trust reported endpoint equality."""

import os

import pytest

from src.governance.store import SqliteStore
from src.governance.tenant_store import TenantStoreDenied, TenantStoreRegistry
from tests.test_authority import authority as authority
from tests.test_tenant_store import namespaces as namespaces


@pytest.mark.parametrize("target", ["tenant", "authority"])
def test_reported_endpoint_difference_cannot_hide_cross_namespace_grants(authority, namespaces, monkeypatch, target):
    directory = authority[0]
    if isinstance(directory.store, SqliteStore):
        pytest.skip("PostgreSQL schema privilege boundary")
    import psycopg
    from psycopg import sql

    a, b = namespaces("alpha"), namespaces("beta")
    protected = b if target == "tenant" else directory.store
    if target == "tenant":
        schema = b.schema
    else:
        schema = protected._db.execute("SELECT current_schema() AS schema").fetchone()["schema"]
    protected.upsert_budget("private-grant-sentinel", {"spent": 47})
    # Model a different reported interface/address without mocking any database
    # privilege query. The grants and direct cross-schema read below are real.
    monkeypatch.setattr(a, "namespace_key", ("postgres", "reported-other-interface", *a.namespace_key[2:]))
    with psycopg.connect(os.environ["AGENTBRIDGE_TEST_PG"], autocommit=True) as admin:
        usage = sql.SQL("{} USAGE ON SCHEMA {} {} {}").format
        select = sql.SQL("{} SELECT ON TABLE {}.budgets {} {}").format
        admin.execute(usage(sql.SQL("GRANT"), sql.Identifier(schema), sql.SQL("TO"), sql.Identifier(a._role)))
        admin.execute(select(sql.SQL("GRANT"), sql.Identifier(schema), sql.SQL("TO"), sql.Identifier(a._role)))
        try:
            row = a._db.execute(sql.SQL("SELECT COUNT(*) AS count FROM {}.budgets").format(sql.Identifier(schema))).fetchone()
            assert row["count"] >= 1
            with pytest.raises(TenantStoreDenied, match="another tenant or authority"):
                TenantStoreRegistry(directory, {"alpha": a, "beta": b})
        finally:
            admin.execute(select(sql.SQL("REVOKE"), sql.Identifier(schema), sql.SQL("FROM"), sql.Identifier(a._role)))
            admin.execute(usage(sql.SQL("REVOKE"), sql.Identifier(schema), sql.SQL("FROM"), sql.Identifier(a._role)))
    # Different reported metadata alone must not reject correctly separated roles.
    TenantStoreRegistry(directory, {"alpha": a, "beta": b})
