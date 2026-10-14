"""
Shared pytest fixtures for AgentBridge tests.

Uses the REAL governance API (see src/governance). Fixtures are opt-in — a test only
pays for one it requests by name — so this file adds reusable setup without changing
how the existing self-contained tests run.
"""

import os
import sys

import pytest

# Make `src` importable however pytest is invoked — bare `pytest` (as CI runs it) does not put
# the repo root on sys.path the way `python -m pytest` does.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.governance import (
    AgentIdentity,
    BudgetManager,
    BusinessHoursOnly,
    DenyCapabilities,
    IdentityRegistry,
    MaxCostPerCall,
    PolicySet,
    RequireApprovalAboveCost,
    make_store,
)


@pytest.fixture
def in_memory_store():
    """A fresh in-memory governance store."""
    return make_store(None)


@pytest.fixture
def sqlite_store(tmp_path):
    """A durable SQLite store in a per-test temp dir (closed on teardown)."""
    store = make_store(str(tmp_path / "governance.db"))
    yield store
    if hasattr(store, "close"):
        store.close()


@pytest.fixture
def sample_identity():
    """A freshly generated Ed25519 agent identity."""
    return AgentIdentity.generate("agent-test-001")


@pytest.fixture
def identities(sample_identity):
    """An IdentityRegistry with one registered agent."""
    reg = IdentityRegistry()
    reg.register(sample_identity)
    return reg


@pytest.fixture
def budgets(in_memory_store):
    """A store-backed BudgetManager."""
    return BudgetManager(store=in_memory_store)


@pytest.fixture
def sample_policy():
    """A representative PolicySet using the real rule signatures."""
    return PolicySet([
        MaxCostPerCall(10),
        RequireApprovalAboveCost(5),
        DenyCapabilities(["wire_transfer"]),
        BusinessHoursOnly(9, 17, days=[0, 1, 2, 3, 4]),
    ])

@pytest.fixture
def loopback_server():
    """Serve one real local HTTP app and release only its listener/thread."""
    import socket
    import threading
    import time
    from contextlib import contextmanager

    import uvicorn

    @contextmanager
    def serve(factory):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        url = "http://127.0.0.1:" + str(listener.getsockname()[1])
        app = factory(url)
        server = uvicorn.Server(uvicorn.Config(app, lifespan="on", access_log=False,
                                             log_level="critical", timeout_graceful_shutdown=.2))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        try:
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise AssertionError("loopback server failed to start")
                time.sleep(.01)
            yield url, app
        finally:
            server.should_exit = True
            thread.join(5)
            listener.close()
            assert not thread.is_alive(), "loopback server did not stop"

    return serve

@pytest.fixture(params=["sqlite", "postgres"])
def network_sql_stores(request, tmp_path):
    """Private per-test SQL namespace shared across restart handles."""
    import uuid

    from src.governance.store import PostgresStore, SqliteStore

    handles = []
    if request.param == "sqlite":
        def factory():
            store = SqliteStore(str(tmp_path / "network-status.sqlite"))
            handles.append(store)
            return store
        try:
            yield factory
        finally:
            for store in handles:
                store.close()
    else:
        dsn = os.getenv("AGENTBRIDGE_TEST_PG")
        if not dsn:
            pytest.skip("explicit disposable PostgreSQL required")
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        schema = "ab_network_" + uuid.uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            def factory():
                store = PostgresStore(make_conninfo(dsn, options="-csearch_path=" + schema))
                handles.append(store)
                return store
            try:
                yield factory
            finally:
                for store in handles:
                    store.close()
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
