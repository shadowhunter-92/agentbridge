"""Root-granted disposable PostgreSQL trials; retain baseline failures.

Only UUID-scoped rows are touched. Immutable e052 classes are loaded from the
local Git object database for comparison; no fetch or source mutation occurs.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import subprocess
import threading
import time
from types import ModuleType, SimpleNamespace
import uuid

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from src.governance import fenced_postgres_destination as working_destination
from src.governance import pg_fencing as working_fencing


BASE = "e0521ad67d7f05e4bec55685cdbb91c96fd158f0"
ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "src/governance/pg_fencing.py": "10d6bc700bfd065715410ed412a4493da0827f667f5a76933dd6eec17d5d0218",
    "src/governance/fenced_postgres_destination.py": "9901b2c5f614d891323cf0703b4d3db96e49c54f24a3df5533442eab9531d1ce",
}
pytestmark = pytest.mark.skipif(
    not os.getenv("AGENTBRIDGE_TEST_PG"), reason="exclusive disposable PostgreSQL grant required"
)


def _immutable_module(path, name):
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", BASE + ":" + path],
        capture_output=True, check=True, timeout=10,
    )
    assert hashlib.sha256(result.stdout).hexdigest() == PINS[path]
    module = ModuleType("src.governance." + name)
    module.__package__ = "src.governance"
    exec(compile(result.stdout, BASE + ":" + path, "exec"), module.__dict__)
    return module


@pytest.fixture(params=(
    ("e052", "working") if os.getenv("AGENTBRIDGE_HA_COMPARE_BASELINE") == "1" else ("working",)
))
def implementation(request):
    if request.param == "e052":
        lease = _immutable_module("src/governance/pg_fencing.py", "_ha_e052_fencing")
        target = _immutable_module(
            "src/governance/fenced_postgres_destination.py", "_ha_e052_destination"
        )
    else:
        lease, target = working_fencing, working_destination
    return SimpleNamespace(name=request.param, lease=lease, target=target)


@dataclass
class Case:
    dsn: str = field(repr=False)
    application: str
    scope: str
    agent: str
    operation: str
    lease: object
    target: object
    errors: object

    def commit(self, owner, epoch, *, operation=None, lose_ack=False):
        return self.target.commit(
            scope=self.scope, owner=owner, epoch=epoch, agent_id=self.agent,
            operation_id=operation or self.operation, fingerprint="ha-exact-fingerprint",
            lose_ack=lose_ack,
        )


@pytest.fixture
def pg_case(implementation):
    stamp = uuid.uuid4().hex
    # Baseline safety ceiling is deliberately weaker than the unit's own bounds.
    # It bounds a first failing trial without substituting for the 5-second fix.
    dsn = make_conninfo(
        os.environ["AGENTBRIDGE_TEST_PG"],
        options="-cstatement_timeout=7000 -clock_timeout=6000",
        application_name="ab_ha_" + stamp, connect_timeout=5,
    )
    case = Case(
        dsn, "ab_ha_" + stamp, "ha-deadline-" + stamp,
        "ha-deadline-agent-" + stamp, "ha-deadline-operation-" + stamp,
        implementation.lease.PgFencing(dsn),
        implementation.target.FencedPostgresDestination(dsn, sign=lambda _: bytes(64)),
        implementation,
    )
    case.lease.initialize()
    case.target.initialize()
    try:
        yield case
    finally:
        # Exact owned keys only; never truncate or modify another trial's rows.
        with psycopg.connect(dsn, autocommit=True) as cleanup:
            cleanup.execute(
                "DELETE FROM public.ab_evidence_effects WHERE agent_id=%s", (case.agent,)
            )
            cleanup.execute(
                "DELETE FROM public.agentbridge_fences WHERE scope=%s", (case.scope,)
            )


def _effects(case):
    with psycopg.connect(case.dsn, autocommit=True) as check:
        return check.execute(
            "SELECT operation_id,fingerprint,outcome,receipt_json "
            "FROM public.ab_evidence_effects WHERE agent_id=%s ORDER BY operation_id",
            (case.agent,),
        ).fetchall()


def _row(case):
    with psycopg.connect(case.dsn, autocommit=True) as check:
        return check.execute(
            "SELECT owner,epoch,expires FROM public.agentbridge_fences WHERE scope=%s",
            (case.scope,),
        ).fetchone()


def _wait_for_expiry(connection, scope, *, deadline=3):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if connection.execute(
            "SELECT expires<=clock_timestamp() FROM public.agentbridge_fences WHERE scope=%s",
            (scope,),
        ).fetchone() == (True,):
            return
        time.sleep(.02)
    raise AssertionError("database clock did not establish lease expiry within trial bound")


def _wait_for_row_lock(connection, application):
    end = time.monotonic() + 1
    while time.monotonic() < end:
        # Refresh this observer transaction only; never reset server counters.
        # https://www.postgresql.org/docs/16/monitoring-stats.html
        connection.execute("SELECT pg_stat_clear_snapshot()")
        if connection.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE application_name=%s "
            "AND pid<>pg_backend_pid() AND wait_event_type='Lock'",
            (application,),
        ).fetchone() == (1,):
            return
        time.sleep(.01)
    raise AssertionError("worker was not observed waiting on the exact trial connection")


def _outcome(call):
    started = time.monotonic()
    try:
        return dict(result=call(), error=None, elapsed=time.monotonic() - started)
    except Exception as error:
        return dict(result=None, error=error, elapsed=time.monotonic() - started)


@pytest.mark.parametrize("method", ("acquire", "renew", "commit"))
def test_held_fence_lock_has_own_five_second_sql_bound(
    pg_case, method, monkeypatch, record_property
):
    case = pg_case
    epoch = case.lease.acquire(case.scope, "worker", ttl_seconds=30)
    settings = []
    real_connect = psycopg.connect

    def observed_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        if kwargs.get("application_name") is None:
            def setting(name):
                row = connection.execute("SHOW " + name).fetchone()
                return row[name] if isinstance(row, dict) else row[0]

            settings.append((
                setting("lock_timeout"),
                setting("statement_timeout"),
            ))
            # End the observer read transaction; do not retain unrelated locks.
            if not connection.autocommit:
                connection.commit()
        return connection

    # Open the lock holder before observing only the worker's new connection.
    with real_connect(case.dsn, autocommit=True) as holder:
        with holder.transaction(), ThreadPoolExecutor(max_workers=1) as pool:
            holder.execute(
                "SELECT 1 FROM public.agentbridge_fences WHERE scope=%s FOR UPDATE",
                (case.scope,),
            )
            monkeypatch.setattr(psycopg, "connect", observed_connect)
            call = (lambda: case.lease.acquire(case.scope, "contender")) if method == "acquire" else (
                (lambda: case.lease.renew(case.scope, "worker", epoch)) if method == "renew"
                else (lambda: case.commit("worker", epoch))
            )
            future = pool.submit(_outcome, call)
            _wait_for_row_lock(holder, case.application)
            outcome = future.result(timeout=9)
    monkeypatch.setattr(psycopg, "connect", real_connect)
    record_property("lock_wait_seconds", round(outcome["elapsed"], 3))
    record_property("observed_server_timeouts", repr(settings))
    assert isinstance(outcome["error"], psycopg.errors.LockNotAvailable)
    assert outcome["result"] is None
    assert 4 <= outcome["elapsed"] < 9
    assert settings == [("5s", "10s")]
    assert _effects(case) == []
    assert _row(case)[:2] == ("worker", epoch)


def test_concurrent_acquire_has_one_live_owner_and_one_effect(pg_case):
    case = pg_case
    barrier = threading.Barrier(8)

    def contender(index):
        owner = "worker-" + str(index)
        barrier.wait(timeout=5)
        try:
            return owner, case.lease.acquire(case.scope, owner), None
        except case.errors.lease.FenceDenied as error:
            return owner, None, error

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(contender, range(8)))
    winners = [(owner, epoch) for owner, epoch, error in outcomes if error is None]
    assert len(winners) == 1
    assert sum(error is not None for _, _, error in outcomes) == 7
    owner, epoch = winners[0]
    assert case.lease.check(case.scope, owner, epoch)
    for loser, _, error in outcomes:
        if error is not None:
            with pytest.raises(case.errors.target.StaleDestinationLeader):
                case.commit(loser, epoch)
    case.commit(owner, epoch)
    assert len(_effects(case)) == 1


def test_expiry_handoff_denies_old_owner_renewal_and_effect(pg_case):
    case = pg_case
    old = case.lease.acquire(case.scope, "old-worker", ttl_seconds=.6)
    with psycopg.connect(case.dsn, autocommit=True) as clock:
        _wait_for_expiry(clock, case.scope)
    new = case.lease.acquire(case.scope, "new-worker", ttl_seconds=30)
    assert new > old
    assert not case.lease.check(case.scope, "old-worker", old)
    with pytest.raises(case.errors.lease.FenceDenied, match="stale or expired"):
        case.lease.renew(case.scope, "old-worker", old)
    with pytest.raises(case.errors.target.StaleDestinationLeader):
        case.commit("old-worker", old)
    case.commit("new-worker", new)
    assert len(_effects(case)) == 1


def test_lost_ack_has_durable_cross_connection_readback_and_no_second_effect(pg_case):
    case = pg_case
    epoch = case.lease.acquire(case.scope, "worker")
    with pytest.raises(TimeoutError, match="commit succeeded but ACK was lost"):
        case.commit("worker", epoch, lose_ack=True)
    rows = _effects(case)
    assert len(rows) == 1
    operation, fingerprint, outcome, receipt = rows[0]
    assert (operation, fingerprint, outcome) == (
        case.operation, "ha-exact-fingerprint", "succeeded"
    )
    assert receipt == dict(
        agent_id=case.agent, operation_id=case.operation,
        fingerprint="ha-exact-fingerprint", outcome="succeeded",
        external_reference="pg-fenced-effect:" + case.operation,
        signature_hex=bytes(64).hex(),
    )
    with pytest.raises(case.errors.target.DuplicateDestinationAction):
        case.commit("worker", epoch)
    assert _effects(case) == rows


@pytest.mark.parametrize("method", ("renew", "commit"))
@pytest.mark.parametrize("isolation", ("read committed", "repeatable read", "serializable"))
def test_unchanged_row_lock_released_after_expiry_cannot_resurrect_or_execute(
    pg_case, method, isolation, record_property
):
    case = pg_case
    # Observe the selected isolation on an actual new transaction. Keep the
    # same lock-wait stimulus and precise refusal/state assertions in all modes.
    options = conninfo_to_dict(case.dsn).get("options", "")
    options += " -cdefault_transaction_isolation=" + isolation.replace(" ", "\\ ")
    case.dsn = make_conninfo(case.dsn, options=options)
    case.lease.dsn = case.target.dsn = case.dsn
    with psycopg.connect(case.dsn) as observer:
        observed_isolation = observer.execute("SHOW transaction_isolation").fetchone()[0]
    assert observed_isolation == isolation
    record_property("transaction_isolation", observed_isolation)
    epoch = case.lease.acquire(case.scope, "worker", ttl_seconds=1.5)
    original = _row(case)
    with psycopg.connect(case.dsn, autocommit=True) as holder:
        holder.execute("BEGIN")
        released = False
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                held_at = time.monotonic()
                holder.execute(
                    "SELECT 1 FROM public.agentbridge_fences WHERE scope=%s FOR UPDATE",
                    (case.scope,),
                )
                call = (lambda: case.lease.renew(case.scope, "worker", epoch)) if method == "renew" else (
                    lambda: case.commit("worker", epoch)
                )
                future = pool.submit(_outcome, call)
                _wait_for_row_lock(holder, case.application)
                assert holder.execute(
                    "SELECT expires>clock_timestamp() FROM public.agentbridge_fences WHERE scope=%s",
                    (case.scope,),
                ).fetchone() == (True,), "worker did not block while the lease was still live"
                _wait_for_expiry(holder, case.scope)
                assert time.monotonic() - held_at < 4, "hold crossed the unrelated lock timeout"
                # Release ONLY the unchanged row before joining the worker.
                holder.execute("COMMIT")
                released = True
                outcome = future.result(timeout=5)
            finally:
                if not released:
                    holder.execute("ROLLBACK")
    record_property("post_expiry_call_seconds", round(outcome["elapsed"], 3))
    observed, effects = _row(case), _effects(case)
    record_property("post_wait_error_type", type(outcome["error"]).__name__)
    record_property("lease_owner_epoch_unchanged", observed[:2] == original[:2])
    record_property("lease_expiry_unchanged", observed[2] == original[2])
    record_property("post_wait_effect_count", len(effects))
    expected = case.errors.lease.FenceDenied if method == "renew" else (
        case.errors.target.StaleDestinationLeader
    )
    assert isinstance(outcome["error"], expected), "expired blocked call did not refuse with its precise family"
    assert outcome["result"] is None
    assert observed == original, "expired lease was renewed or rewritten"
    assert effects == [], "expired worker committed an effect"
