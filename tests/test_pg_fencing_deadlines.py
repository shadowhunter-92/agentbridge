"""Offline fail-closed deadline contracts; no PostgreSQL or sockets are used.

The controlled backend observes connection options and models database errors.
It cannot establish PostgreSQL row-lock/clock evaluation or topology guarantees.
"""
from contextlib import contextmanager
from pathlib import Path
import shlex

import psycopg
import pytest

from src.governance import fenced_postgres_destination as destination
from src.governance import pg_fencing as fencing


DSN = "dbname=agentbridge_test host=127.0.0.1 port=5432 user=offline_only"
METHODS = ("initialize", "acquire", "renew", "check", "destination_initialize", "commit")


class Backend:
    def __init__(self):
        self.connections = []
        self.queries = []
        self.events = []
        self.fence = {"owner": "worker", "epoch": 2, "live": True}
        self.epoch = (2,)
        self.error = None
        self.error_stage = None
        self.pending = 0
        self.effects = 0
        self.row_locked = False
        self.expired_while_waiting = False

    def connect(self, dsn, **kwargs):
        self.connections.append((dsn, kwargs))
        if self.error_stage == "connect":
            raise self.error
        return self

    def __enter__(self):
        self.events.append("connection-enter")
        return self

    def __exit__(self, kind, value, traceback):
        self.events.append("connection-rollback" if kind else "connection-exit")
        if kind:
            self.pending = 0
        return False

    @contextmanager
    def transaction(self):
        self.events.append("transaction-enter")
        try:
            yield self
        except BaseException:
            self.pending = 0
            self.events.append("transaction-rollback")
            raise
        else:
            self.effects += self.pending
            self.pending = 0
            self.events.append("transaction-commit")

    def execute(self, query, values=()):
        self.queries.append((query, values))
        if self.error_stage == "execute":
            raise self.error
        if query.endswith("FOR UPDATE"):
            self.row_locked = True
        if query.startswith("INSERT INTO public.ab_evidence_effects"):
            if self.error_stage == "insert":
                raise self.error
            self.pending += 1
        self.last_query = query
        return self

    def fetchone(self):
        if self.last_query.startswith("SELECT 1") and self.last_query.endswith("FOR UPDATE"):
            return (1,) if self.fence is not None else None
        if self.last_query.startswith("SELECT owner,epoch"):
            if self.expired_while_waiting and not self.last_query.endswith("FOR UPDATE"):
                return dict(self.fence, live=False)
            return self.fence
        if self.last_query.startswith("UPDATE") and self.expired_while_waiting:
            return None if self.row_locked else self.epoch
        if self.last_query.startswith("SELECT 1"):
            return self.epoch
        return self.epoch


@pytest.fixture
def backend(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    assert Path(fencing.__file__).resolve() == root / "src/governance/pg_fencing.py"
    assert Path(destination.__file__).resolve() == root / "src/governance/fenced_postgres_destination.py"
    instance = Backend()
    monkeypatch.setattr(psycopg, "connect", instance.connect)
    return instance


def invoke(method, *, dsn=DSN, sign=lambda _: bytes(64), lose_ack=False):
    service = fencing.PgFencing(dsn)
    if method == "initialize":
        return service.initialize()
    if method == "acquire":
        return service.acquire("scope", "worker")
    if method == "renew":
        return service.renew("scope", "worker", 2)
    if method == "check":
        return service.check("scope", "worker", 2)
    target = destination.FencedPostgresDestination(dsn, sign=sign)
    if method == "destination_initialize":
        return target.initialize()
    return target.commit(scope="scope", owner="worker", epoch=2,
                         agent_id="agent", operation_id="operation",
                         fingerprint="fingerprint", lose_ack=lose_ack)


def effective_gucs(options):
    result = {}
    tokens = iter(shlex.split(options))
    for token in tokens:
        if token == "-c":
            token = next(tokens)
        elif token.startswith("-c"):
            token = token[2:]
        else:
            continue
        key, value = token.split("=", 1)
        result[key] = value
    return result


@pytest.mark.parametrize("method", METHODS)
def test_each_database_entry_has_explicit_connection_statement_and_lock_bounds(backend, method):
    invoke(method)
    assert len(backend.connections) == 1
    dsn, options = backend.connections[0]
    assert dsn == DSN
    assert options.get("connect_timeout") == 5
    assert effective_gucs(options.get("options", ""))["statement_timeout"] == "10000"
    assert effective_gucs(options["options"])["lock_timeout"] == "5000"
    if method in METHODS[:4]:
        assert options["autocommit"] is True
    elif method == "commit":
        assert options["row_factory"] is destination.dict_row


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("dsn", (
    DSN + " options='-c search_path=tenant_alpha -cstatement_timeout=0 -clock_timeout=0'",
    "postgresql://offline_only@127.0.0.1/agentbridge_test?options=-csearch_path%3Dtenant_alpha%20-cstatement_timeout%3D0%20-clock_timeout%3D0",
))
def test_preserve_trusted_namespace_but_do_not_accept_weaker_sql_deadlines(backend, method, dsn):
    invoke(method, dsn=dsn)
    original, options = backend.connections[0]
    assert original == dsn
    gucs = effective_gucs(options.get("options", ""))
    assert gucs.get("search_path") == "tenant_alpha"
    assert gucs.get("statement_timeout") == "10000"
    assert gucs.get("lock_timeout") == "5000"
    assert options["connect_timeout"] == 5


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("stage,error_type", (
    ("connect", psycopg.OperationalError),
    ("execute", psycopg.errors.QueryCanceled),
    ("execute", psycopg.errors.LockNotAvailable),
))
def test_database_timeout_errors_propagate_without_retry_or_effect(backend, method, stage, error_type):
    error = error_type("controlled offline database timeout")
    backend.error, backend.error_stage = error, stage
    with pytest.raises(error_type) as caught:
        invoke(method)
    assert caught.value is error
    assert len(backend.connections) == 1
    assert len(backend.queries) == (0 if stage == "connect" else 1)
    assert backend.pending == backend.effects == 0
    if method == "commit" and stage == "execute":
        assert "transaction-rollback" in backend.events


@pytest.mark.parametrize("fence", (None,
    {"owner": "old-worker", "epoch": 2, "live": True},
    {"owner": "worker", "epoch": 1, "live": True},
    {"owner": "worker", "epoch": 2, "live": False},
))
def test_stale_missing_and_expired_fence_never_reaches_effect_insert(backend, fence):
    backend.fence = fence
    with pytest.raises(destination.StaleDestinationLeader, match="stale or expired"):
        invoke("commit")
    assert len(backend.connections) == 1
    assert len(backend.queries) == (1 if fence is None else 2)
    assert backend.pending == backend.effects == 0
    assert "transaction-rollback" in backend.events


@pytest.mark.parametrize("error_type", (psycopg.errors.QueryCanceled, psycopg.errors.LockNotAvailable))
def test_effect_insert_timeout_rolls_back_without_retry(backend, error_type):
    backend.error_stage, backend.error = "insert", error_type("controlled effect timeout")
    with pytest.raises(error_type):
        invoke("commit")
    assert len(backend.connections) == 1
    assert len(backend.queries) == 3
    assert backend.pending == backend.effects == 0
    assert "transaction-rollback" in backend.events


def test_lost_ack_remains_ambiguous_after_one_durable_effect(backend):
    with pytest.raises(TimeoutError, match="commit succeeded but ACK was lost"):
        invoke("commit", lose_ack=True)
    assert len(backend.connections) == 1
    assert len(backend.queries) == 3
    assert backend.effects == 1 and backend.pending == 0
    assert "transaction-commit" in backend.events


def test_duplicate_effect_keeps_existing_error_family_and_does_not_retry(backend):
    backend.error_stage = "insert"
    backend.error = psycopg.errors.UniqueViolation("controlled duplicate")
    with pytest.raises(destination.DuplicateDestinationAction) as caught:
        invoke("commit")
    assert caught.value.__cause__ is backend.error
    assert len(backend.connections) == 1
    assert backend.effects == backend.pending == 0


@pytest.mark.parametrize("method", ("acquire", "renew"))
def test_existing_default_ttl_and_epoch_sql_parameters_are_preserved(backend, method):
    assert invoke(method) == 2
    _, parameters = backend.queries[-1]
    assert parameters == (("scope", "worker", 30, 30) if method == "acquire"
                          else (30, "scope", "worker", 2))
    if method == "renew":
        assert backend.queries[0] == (
            "SELECT 1 FROM agentbridge_fences WHERE scope=%s FOR UPDATE", ("scope",)
        )


@pytest.mark.parametrize("method", ("acquire", "renew", "check"))
def test_no_lease_row_is_not_misreported_as_leadership(backend, method):
    backend.epoch = None
    if method == "check":
        assert invoke(method) is False
    else:
        with pytest.raises(fencing.FenceDenied):
            invoke(method)
    assert len(backend.connections) == 1
    assert len(backend.queries) == (2 if method == "renew" else 1)


@pytest.mark.parametrize("bad_signature", (None, b"short", "not bytes"))
def test_invalid_signer_result_denies_before_database_connection(backend, bad_signature):
    with pytest.raises(ValueError, match="invalid destination signer"):
        invoke("commit", sign=lambda _: bad_signature)
    assert backend.connections == backend.queries == []


def test_renew_missing_locked_row_refuses_before_update(backend):
    backend.fence = None
    # A subsequent write returning an epoch must never be reached.
    backend.epoch = (2,)
    with pytest.raises(fencing.FenceDenied, match="stale or expired"):
        invoke("renew")
    assert len(backend.connections) == 1
    assert backend.queries == [(
        "SELECT 1 FROM agentbridge_fences WHERE scope=%s FOR UPDATE", ("scope",)
    )]
    assert "transaction-rollback" in backend.events
    assert backend.pending == backend.effects == 0


@pytest.mark.parametrize("method", ("renew", "commit"))
def test_expiry_observed_after_lock_refuses_pre_wait_live_snapshot(backend, method):
    # The pre-wait snapshot still looks live. A separate post-lock statement
    # sees expiry; a stale projection or UPDATE issued first would succeed.
    backend.expired_while_waiting = True
    expected = fencing.FenceDenied if method == "renew" else destination.StaleDestinationLeader
    with pytest.raises(expected, match="stale or expired"):
        invoke(method)
    assert len(backend.connections) == 1
    assert len(backend.queries) == 2
    lock_query, lock_values = backend.queries[0]
    fresh_query, _ = backend.queries[1]
    assert lock_query.endswith("FOR UPDATE") and lock_values == ("scope",)
    assert "clock_timestamp()" not in lock_query
    assert "clock_timestamp()" in fresh_query and "FOR UPDATE" not in fresh_query
    assert backend.row_locked
    assert backend.effects == backend.pending == 0
    if method == "commit":
        assert "transaction-rollback" in backend.events
