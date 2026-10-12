"""Versioned PostgreSQL migration rolls back only if it cannot lose live fence data."""
import os
import uuid
import pytest

pytestmark=pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG"),
                              reason="disposable PostgreSQL required")


def test_versioned_postgres_fence_migration_apply_reapply_and_safe_downgrade():
    import psycopg
    from psycopg import sql
    from src.governance.schema_migrations import FencingMigration,MigrationDenied

    dsn=os.environ["AGENTBRIDGE_TEST_PG"]
    schema="ab_migrate_"+uuid.uuid4().hex[:14]
    with psycopg.connect(dsn,autocommit=True) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            m=FencingMigration(dsn,schema)
            assert m.apply() is True
            assert m.apply() is False
            with psycopg.connect(dsn) as work:
                work.execute(sql.SQL(
                    "INSERT INTO {} (scope,owner,epoch,expires) "
                    "VALUES ('test','operator',1,clock_timestamp()+interval '10 seconds')"
                ).format(sql.Identifier(schema,"agentbridge_fences")))
            with pytest.raises(MigrationDenied,match="live state"):
                m.rollback()
            with psycopg.connect(dsn) as work:
                work.execute(sql.SQL("DELETE FROM {}").format(
                    sql.Identifier(schema,"agentbridge_fences")))
            assert m.rollback() is True
            assert m.rollback() is False
            row=c.execute("SELECT to_regclass(%s)",(
                schema+".agentbridge_fences",)).fetchone()
            assert row[0] is None
        finally:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
