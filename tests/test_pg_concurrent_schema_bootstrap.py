"""Concurrent first-use PostgreSQL schema bootstrap must be race-free."""
import concurrent.futures
import os
import uuid
import pytest

pytestmark=pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG"),
                              reason="needs isolated PostgreSQL test service")


def test_eight_workers_bootstrap_same_fresh_schema_without_catalog_race():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from src.governance.store import PostgresStore
    base=os.environ["AGENTBRIDGE_TEST_PG"]
    schema="ab_bootstrap_"+uuid.uuid4().hex[:16]
    with psycopg.connect(base,autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            dsn=make_conninfo(base,options="-c search_path="+schema)
            def worker(index):
                db=PostgresStore(dsn)
                try:
                    agent="worker-"+str(index)
                    db.upsert_identity(agent,"ci-public-test")
                    return db.get_identity(agent)["agent_id"]
                finally:
                    db.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                outcome=list(pool.map(worker,range(8)))
            assert len(set(outcome))==8
            with psycopg.connect(dsn) as check:
                count=check.execute("SELECT count(*) FROM identities").fetchone()[0]
                assert count==8
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(
                sql.Identifier(schema)))
