"""Offline worker/drill contracts with explicit capability guards.

Fakes exercise reporting/control flow only. They do not qualify PostgreSQL,
OS-process isolation, real partitions, physical failover or governed recovery.
Guards refuse psycopg.connect, multiprocessing.get_context, subprocess.Popen
and socket.create_connection; this is not a sandbox for arbitrary imported code.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import queue
import socket
import subprocess
from types import SimpleNamespace

import pytest

from tools import drill_pg_stale_leader as drill


DSN = "host=127.0.0.1 port=15432 dbname=agentbridge_test user=offline password=fake-only"
SECRET = "must-not-appear-in-report"


@pytest.fixture(autouse=True)
def offline_boundary(monkeypatch):
    assert Path(drill.__file__).resolve() == Path(__file__).resolve().parents[1] / "tools/drill_pg_stale_leader.py"
    attempts = []
    def guard(name):
        def forbidden(*args, **kwargs):
            attempts.append(name)
            raise AssertionError("offline harness attempted an external capability")
        return forbidden
    monkeypatch.setattr(drill.psycopg, "connect", guard("psycopg.connect"))
    monkeypatch.setattr(drill.multiprocessing, "get_context", guard("multiprocessing.get_context"))
    monkeypatch.setattr(socket, "create_connection", guard("socket.create_connection"))
    monkeypatch.setattr(subprocess, "Popen", guard("subprocess.Popen"))
    monkeypatch.setenv("AGENTBRIDGE_ENV", "test")
    monkeypatch.delenv("AGENTBRIDGE_TEST_PG", raising=False)
    monkeypatch.delenv("AGENTBRIDGE_STALE_LEADER_REPORT", raising=False)
    yield
    assert attempts == [], "a caught capability denial must not become a passing negative"


class Clock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.now += seconds


def resolve(outcome):
    if callable(outcome):
        outcome = outcome()
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome


class Lease:
    def __init__(self, acquire=(1,), renew=(1, 1, drill.FenceDenied("stale"))):
        self.acquire_results, self.renew_results = list(acquire), list(renew)
        self.calls = []
    def acquire(self, *args, **kwargs):
        self.calls.append(("acquire", args, kwargs))
        assert self.acquire_results, "unexpected acquire/retry"
        return resolve(self.acquire_results.pop(0))
    def renew(self, *args, **kwargs):
        self.calls.append(("renew", args, kwargs))
        assert self.renew_results, "unexpected renew/retry"
        return resolve(self.renew_results.pop(0))


class Target:
    def __init__(self, outcome=None):
        self.outcome, self.calls = outcome, []
    def commit(self, **kwargs):
        self.calls.append(kwargs)
        return resolve(self.outcome)


class Barrier:
    def __init__(self, result=True, error=None):
        self.result, self.error, self.waits, self.sets = result, error, [], 0
    def wait(self, seconds):
        self.waits.append(seconds)
        return resolve(self.result)
    def set(self):
        self.sets += 1
        if self.error:
            raise self.error


def run_worker(role="replacement", *, lease=None, target=None, clock=None, resume=None, **bounds):
    clock, lease = clock or Clock(), lease or Lease()
    target = target or Target(TimeoutError(SECRET))
    resume, events = resume or Barrier(), []
    result = drill._participating_lease_loop(
        lease=lease, target=target, role=role, scope="owned-scope", owner=role,
        operation_id="one-operation", agent_id="owned-agent", fingerprint="approved",
        ttl_seconds=3, renew_interval=bounds.get("renew_interval", .25),
        window_seconds=bounds.get("window_seconds", 12), resume=resume, emit=events.append,
        clock=clock, sleep=clock.sleep)
    assert result["dispatch_stopped"] is True
    assert SECRET not in json.dumps(result)
    return result, lease, target, events


def test_replacement_lost_ack_is_one_attempt_without_reacquisition_or_replay():
    result, lease, target, events = run_worker()
    assert result["state"] == "effect-return-unknown"
    assert result["counts"]["effect_return_unknown"] == 1
    assert [call[0] for call in lease.calls] == ["acquire"]
    assert target.calls == [dict(scope="owned-scope", owner="replacement", epoch=1,
                                agent_id="owned-agent", operation_id="one-operation",
                                fingerprint="approved", lose_ack=True)]
    assert [event["kind"] for event in events] == ["lease-acquired", "effect-return-unknown"]


def test_known_acquire_refusal_can_retry_without_changing_identity():
    lease = Lease(acquire=(drill.FenceDenied("busy"), drill.FenceDenied("busy"), 4))
    result, lease, target, _ = run_worker(lease=lease)
    assert result["counts"]["acquire_refusals"] == 2
    assert result["counts"]["acquire_attempts"] == 3
    assert len(target.calls) == 1 and target.calls[0]["epoch"] == 4
    assert all(call[1] == ("owned-scope", "replacement") for call in lease.calls)


@pytest.mark.parametrize("failure", [TimeoutError(SECRET), ConnectionError(SECRET), RuntimeError(SECRET)])
@pytest.mark.parametrize("phase", ["acquire", "renew"])
def test_uncertain_lease_response_stops_without_retry_or_effect(failure, phase):
    lease = Lease(acquire=(failure,) if phase == "acquire" else (1,), renew=(failure,))
    result, lease, target, _ = run_worker("old", lease=lease)
    assert result["state"] == "lease-response-unknown" and result["phase"] == phase
    assert result["counts"]["lease_response_unknown"] == 1
    assert len(lease.calls) == (1 if phase == "acquire" else 2)
    assert target.calls == []


@pytest.mark.parametrize("bad_epoch", [True, False, None, 0, -1, 1.0, "1"])
def test_invalid_acquisition_epoch_never_dispatches(bad_epoch):
    result, lease, target, _ = run_worker(lease=Lease(acquire=(bad_epoch,)))
    assert result["state"] == "invalid-lease-response"
    assert len(lease.calls) == 1 and target.calls == []


@pytest.mark.parametrize("bad_epoch", [True, None, 0, 2, 1.0, "1"])
def test_invalid_renewal_acknowledgment_stops_without_effect(bad_epoch):
    result, lease, target, _ = run_worker("old", lease=Lease(renew=(bad_epoch,)))
    assert result["state"] == "invalid-lease-response" and result["phase"] == "renew"
    assert len(lease.calls) == 2 and target.calls == []


def test_known_renewal_refusal_stops_without_reacquisition():
    result, lease, target, _ = run_worker("old", lease=Lease(renew=(drill.FenceDenied("revoked"),)))
    assert result["state"] == "lease-refused"
    assert [call[0] for call in lease.calls] == ["acquire", "renew"]
    assert target.calls == []


@pytest.mark.parametrize("result,expected", [(None, "effect-acknowledged"),
    (drill.StaleDestinationLeader("stale"), "destination-refused"),
    (drill.DuplicateDestinationAction("same identity"), "destination-refused"),
    (ValueError(SECRET), "effect-return-unknown")])
def test_replacement_never_regenerates_id_or_retries_after_any_effect_return(result, expected):
    verdict, lease, target, _ = run_worker(target=Target(result))
    assert verdict["state"] == expected
    assert len(target.calls) == 1 and target.calls[0]["operation_id"] == "one-operation"
    assert len(lease.calls) == 1


def test_known_refusal_loop_has_finite_attempt_cap():
    lease = Lease(acquire=[drill.FenceDenied("busy")] * 64)
    result, lease, target, _ = run_worker(lease=lease, renew_interval=.05, window_seconds=45)
    assert result["state"] == "attempt-bound" and len(lease.calls) == 64
    assert result["counts"]["acquire_refusals"] == 64 and target.calls == []


def test_known_refusal_loop_has_finite_observation_window():
    result, lease, target, _ = run_worker(lease=Lease(acquire=[drill.FenceDenied("busy")] * 64),
                                        renew_interval=.25, window_seconds=.5)
    assert result["state"] == "timeout" and len(lease.calls) == 2 and target.calls == []


def test_late_successful_acquire_cannot_dispatch():
    clock = Clock()
    def late():
        clock.now = 13
        return 1
    result, _, target, events = run_worker(clock=clock, lease=Lease(acquire=(late,)))
    assert result["state"] == "timeout" and result["phase"] == "post-acquire"
    assert target.calls == [] and events == []


def test_old_worker_renews_twice_drains_then_uses_distinct_stale_probes():
    result, lease, target, events = run_worker("old", target=Target(drill.StaleDestinationLeader("stale")))
    assert result["state"] == "stale-probes-complete"
    assert result["counts"]["renew_acknowledgments"] == 2
    assert result["counts"]["stale_renew_refusals"] == result["counts"]["stale_effect_refusals"] == 1
    assert [call[0] for call in lease.calls] == ["acquire", "renew", "renew", "renew"]
    assert len(target.calls) == 1 and "lose_ack" not in target.calls[0]
    assert [event["kind"] for event in events] == ["lease-acquired", "lease-renewed", "lease-renewed",
                                                 "renewal-drained", "stale-renewal-refused", "stale-effect-refused"]


def test_drained_worker_barrier_timeout_never_probes_or_dispatches():
    result, lease, target, _ = run_worker("old", resume=Barrier(False))
    assert result["state"] == "timeout" and result["phase"] == "drained"
    assert len(lease.calls) == 3 and target.calls == []


@pytest.mark.parametrize("renewal,expected", [(1, "unsafe-stale-renewal"),
                                          (TimeoutError(SECRET), "lease-response-unknown")])
def test_resumed_old_worker_stops_if_stale_renewal_is_not_precisely_refused(renewal, expected):
    result, lease, target, _ = run_worker("old", lease=Lease(renew=(1, 1, renewal)))
    assert result["state"] == expected and target.calls == [] and len(lease.calls) == 4


@pytest.mark.parametrize("effect,expected", [(None, "unsafe-stale-effect"),
                                          (TimeoutError(SECRET), "effect-return-unknown"),
                                          (drill.DuplicateDestinationAction("collision"), "effect-return-unknown")])
def test_stale_probe_does_not_misclassify_other_returns_as_fence_refusal(effect, expected):
    result, _, target, _ = run_worker("old", target=Target(effect))
    assert result["state"] == expected and len(target.calls) == 1
    assert result["counts"]["stale_effect_refusals"] == 0


def test_stale_renewal_response_after_deadline_does_not_reach_effect_probe():
    clock = Clock()
    def late_refusal():
        clock.now = 13
        return drill.FenceDenied("stale")
    result, _, target, _ = run_worker("old", clock=clock, lease=Lease(renew=(1, 1, late_refusal)))
    assert result["state"] == "timeout" and target.calls == []


def test_unknown_worker_role_refuses_before_resource_calls():
    with pytest.raises(ValueError):
        run_worker("physical-primary")


class Messages:
    def __init__(self, clock, values=()):
        self.clock, self.values, self.timeouts, self.puts = clock, list(values), [], []
        self.closed, self.cancelled = False, False
        self.close_error, self.cancel_error = None, None
    def get(self, timeout):
        self.timeouts.append(timeout)
        if not self.values:
            self.clock.sleep(timeout)
            raise queue.Empty
        return resolve(self.values.pop(0))
    def put(self, value, timeout):
        self.puts.append((value, timeout))
    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error
    def cancel_join_thread(self):
        self.cancelled = True
        if self.cancel_error:
            raise self.cancel_error


def receive(values, *, predicate=lambda rows: bool(rows), window=1):
    clock, events = Clock(), []
    messages = Messages(clock, values)
    drill._receive_lifecycle_events(messages, events, predicate, window, 0, clock=clock)
    return events, messages


def test_queue_observation_records_parent_monotonic_receipt_time():
    events, messages = receive([dict(kind="lease-acquired", owner="old", epoch=1)])
    assert events == [dict(kind="lease-acquired", owner="old", epoch=1, parent_observed_seconds=0)]
    assert messages.timeouts == [.1]


@pytest.mark.parametrize("message", [None, [], "terminal", {}, {"kind": 1},
                                       {"kind": "x", "payload": "x" * 4096},
                                       {"kind": "x", "payload": float("nan")}])
def test_malformed_oversize_or_nonfinite_queue_message_cannot_pass(message):
    with pytest.raises(ValueError):
        receive([message])


@pytest.mark.parametrize("state", ["worker-harness-error", "timeout", "lease-response-unknown",
                                  "unsafe-stale-effect", "effect-acknowledged"])
def test_unexpected_terminal_fails_parent_observation_promptly(state):
    with pytest.raises(RuntimeError):
        receive([dict(kind="terminal", owner="old", verdict=dict(state=state))])


def test_missing_worker_message_is_bounded():
    with pytest.raises(TimeoutError):
        receive([], window=.25)


def test_queue_message_count_is_bounded():
    with pytest.raises(TimeoutError):
        receive([dict(kind="acquire-refused", owner="old")] * 129, predicate=lambda rows: False)


def test_late_queue_message_is_not_accepted():
    clock, events = Clock(), []
    def late():
        clock.now = 2
        return dict(kind="lease-acquired", owner="old", epoch=1)
    with pytest.raises(TimeoutError):
        drill._receive_lifecycle_events(Messages(clock, [late]), events, bool, 1, 0, clock=clock)
    assert len(events) == 1 and events[0]["parent_observed_seconds"] == 2


class Child:
    def __init__(self, name="owned", *, alive=False, terminate_stops=True, kill_stops=True):
        self.name, self.alive, self.exitcode = name, alive, 0 if not alive else None
        self.terminate_stops, self.kill_stops = terminate_stops, kill_stops
        self.calls, self.errors = [], {}
    def action(self, name, *args):
        self.calls.append((name, *args))
        if name in self.errors:
            raise self.errors[name]
    def join(self, timeout):
        self.action("join", timeout)
    def is_alive(self):
        self.action("is_alive")
        return self.alive
    def terminate(self):
        self.action("terminate")
        if self.terminate_stops:
            self.alive, self.exitcode = False, -15
    def kill(self):
        self.action("kill")
        if self.kill_stops:
            self.alive, self.exitcode = False, -9


def test_clean_child_cleanup_is_observed_without_signal():
    child = Child()
    assert drill._cleanup_lifecycle_children([child]) == [dict(
        name="owned", exitcode=0, terminate_requested=False, kill_requested=False,
        still_alive=False, error_types=[])]
    assert child.calls == [("join", 2), ("is_alive",), ("is_alive",), ("is_alive",)]


@pytest.mark.parametrize("terminate_stops,kill_stops,alive", [(True, True, False),
                                                           (False, True, False), (False, False, True)])
def test_cleanup_escalates_only_owned_children_and_reports_survivors(terminate_stops, kill_stops, alive):
    child = Child(alive=True, terminate_stops=terminate_stops, kill_stops=kill_stops)
    row, = drill._cleanup_lifecycle_children([child])
    assert row["terminate_requested"] and row["kill_requested"] is (not terminate_stops)
    assert row["still_alive"] is alive


@pytest.mark.parametrize("error_stage", ["join", "is_alive", "terminate", "kill"])
def test_cleanup_error_preserves_receipt_and_continues_other_owned_child(error_stage):
    broken = Child(alive=True, terminate_stops=False)
    broken.errors[error_stage] = RuntimeError(SECRET)
    rows = drill._cleanup_lifecycle_children([broken, Child("other")])
    assert "RuntimeError" in rows[0]["error_types"]
    assert rows[1]["name"] == "other" and rows[1]["still_alive"] is False
    assert SECRET not in json.dumps(rows)
    if error_stage == "is_alive":
        assert rows[0]["still_alive"] is None


def test_cleanup_unavailable_child_name_does_not_hide_second_child():
    class Unnamed(Child):
        def __getattribute__(self, name):
            if name == "name":
                raise RuntimeError(SECRET)
            return super().__getattribute__(name)
    rows = drill._cleanup_lifecycle_children([Unnamed(), Child("other")])
    assert rows[0]["name"] is None and rows[0]["error_types"] == ["RuntimeError"]
    assert rows[1]["name"] == "other"


@pytest.mark.parametrize("environment", ["prod", "production", " Production "])
def test_lifecycle_refuses_production_environment(monkeypatch, environment):
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    with pytest.raises(ValueError):
        drill.run_worker_lifecycle_drill(DSN)


@pytest.mark.parametrize("change", [
    "host=localhost", "host=192.0.2.1", "host=::1", "hostaddr=192.0.2.1",
    "dbname=customer", "service=customer", "port=543", "port=65536", "port=wrong",
    "user=''", "password=''",
])
def test_lifecycle_refuses_unsafe_or_ambiguous_target_before_any_resources(change):
    with pytest.raises(ValueError):
        drill.run_worker_lifecycle_drill(DSN + " " + change)


@pytest.mark.parametrize("missing", ["host=127.0.0.1", "port=15432", "dbname=agentbridge_test",
                                     "user=offline", "password=fake-only"])
def test_lifecycle_requires_explicit_connection_route_and_credentials(missing):
    with pytest.raises(ValueError):
        drill.run_worker_lifecycle_drill(DSN.replace(missing, ""))


@pytest.mark.parametrize("name,value", [("ttl_seconds", True), ("ttl_seconds", float("nan")),
    ("ttl_seconds", float("inf")), ("ttl_seconds", .5), ("ttl_seconds", 6),
    ("renew_interval", 0), ("renew_interval", 1.1), ("window_seconds", 11),
    ("window_seconds", 46), ("window_seconds", "30")])
def test_lifecycle_timing_bounds_fail_closed_before_resources(name, value):
    with pytest.raises(ValueError):
        drill.run_worker_lifecycle_drill(DSN, **{name: value})


def test_lifecycle_rebuilds_dsn_without_caller_options_or_pg_defaults(monkeypatch):
    monkeypatch.setenv("PGHOST", "192.0.2.10")
    monkeypatch.setenv("PGOPTIONS", "-csearch_path=customer")
    result = drill.conninfo_to_dict(drill._lifecycle_settings(
        DSN + " options='-cstatement_timeout=0' sslmode=require passfile=ignored", 3, .25, 30))
    assert result["host"] == result["hostaddr"] == "127.0.0.1"
    assert result["port"] == "15432" and result["dbname"] == "agentbridge_test"
    assert result["user"] == "offline" and result["password"] == "fake-only"
    assert result["sslmode"] == "disable" and result["connect_timeout"] == "5"
    assert result["options"] == "-csearch_path=public -cstatement_timeout=10000 -clock_timeout=5000"
    assert "passfile" not in result and "service" not in result


class DriverFixture:
    """Simulate parent observations without actually running child targets."""
    def __init__(self, monkeypatch):
        self.clock, self.queue, self.barrier = Clock(), None, Barrier()
        self.children, self.child_specs, self.observe_calls = [], [], []
        self.rows_mode, self.expiry_mode = "valid", "expired"
        self.child_exit, self.start_failure = 0, None
        self.report, self.receipt_error, self.cleanup_queue_error = None, None, None
        self.initialize_calls, self.verifications = [], []
        monkeypatch.setattr(drill, "time", SimpleNamespace(monotonic=self.clock, sleep=self.clock.sleep))
        monkeypatch.setattr(drill, "PgFencing", lambda dsn: self.initializer("lease"))
        monkeypatch.setattr(drill, "FencedPostgresDestination", lambda dsn, sign: self.initializer("target"))
        monkeypatch.setattr(drill, "_bounded_connection", self.database)
        monkeypatch.setattr(drill, "_lifecycle_observe", self.observe)
        monkeypatch.setattr(drill, "verify_destination_receipt", self.verify)
        monkeypatch.setattr(drill.multiprocessing, "get_context", self.context)
    def initializer(self, name):
        return SimpleNamespace(initialize=lambda: self.initialize_calls.append(name))
    @contextmanager
    def database(self, *args, **kwargs):
        yield SimpleNamespace(execute=lambda query: SimpleNamespace(fetchone=lambda: ("160013", "read committed", "5s", "10s")))
    def context(self, method):
        assert method == "spawn"
        return SimpleNamespace(Event=lambda: self.barrier, Queue=self.make_queue, Process=self.process)
    def make_queue(self, maxsize):
        assert maxsize == 128
        self.queue = Messages(self.clock)
        self.queue.close_error = self.cleanup_queue_error
        return self.queue
    def process(self, *, target, args, name):
        assert target is drill._lifecycle_spawned_worker
        spec = args[2]
        self.child_specs.append(spec)
        child = Child(name)
        child.exitcode = self.child_exit
        def start():
            if self.start_failure == spec["role"]:
                raise RuntimeError(SECRET)
            if spec["role"] == "old":
                self.queue.values.extend([
                    dict(kind="lease-acquired", owner=spec["owner"], epoch=1),
                    dict(kind="lease-renewed", owner=spec["owner"], epoch=1),
                    dict(kind="lease-renewed", owner=spec["owner"], epoch=1),
                    dict(kind="renewal-drained", owner=spec["owner"], epoch=1)])
            else:
                self.queue.values.extend([
                    dict(kind="lease-acquired", owner=spec["owner"], epoch=2),
                    dict(kind="terminal", owner="old-worker", verdict=dict(state="stale-probes-complete", counts=dict(renew_acknowledgments=2))),
                    dict(kind="terminal", owner=spec["owner"], verdict=dict(state="effect-return-unknown", counts=dict(destination_attempts=1)))])
        child.start = start
        self.children.append(child)
        return child
    def observe(self, dsn, scope, agent_id):
        self.observe_calls.append((scope, agent_id))
        if len(self.child_specs) == 1:
            if self.expiry_mode == "missing":
                return None, []
            return dict(owner="old-worker", epoch=1, expired=self.expiry_mode == "expired",
                        expires="recorded-server-time", database_clock="recorded-server-time"), []
        spec = self.child_specs[1]
        receipt = dict(outcome="succeeded", external_reference="exact-reference")
        row = dict(operation_id=spec["operation_id"], fingerprint=spec["fingerprint"],
                   outcome="succeeded", external_reference="exact-reference", receipt_json=receipt)
        state = dict(owner=spec["owner"], epoch=2, expired=False)
        if self.rows_mode == "unavailable":
            raise ConnectionError(SECRET)
        if self.rows_mode == "missing":
            return state, []
        if self.rows_mode == "wrong-operation":
            row["operation_id"] = "different"
        if self.rows_mode == "wrong-fingerprint":
            row["fingerprint"] = "different"
        if self.rows_mode == "failed":
            row["outcome"] = "failed"
        if self.rows_mode == "stale-epoch":
            state["epoch"] = 1
        if self.rows_mode == "wrong-owner":
            state["owner"] = "old-worker"
        if self.rows_mode == "mismatched-receipt":
            row["receipt_json"]["external_reference"] = "different"
        return state, [row, copy.deepcopy(row)] if self.rows_mode == "duplicate" else [row]
    def verify(self, receipt, **kwargs):
        self.verifications.append((receipt, kwargs))
        if self.receipt_error:
            raise self.receipt_error
        return "a" * 64
    def run(self):
        self.report = drill.run_worker_lifecycle_drill(DSN)
        assert SECRET not in json.dumps(self.report)
        assert "fake-only" not in json.dumps(self.report)
        return self.report


def test_fake_driver_success_reports_only_observed_components_not_governed_or_physical_metrics(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    report = fixture.run()
    assert report["accepted"] and report["failure"] is None
    assert report["effect_observation"] == "SIGNED_SUCCEEDED_IN_CONTROLLED_DATABASE"
    assert report["old_epoch"] == 1 and report["new_epoch"] == 2
    assert report["separate_connection_observed_effect_count"] == 1 and report["stale_effect_count"] == 0
    assert fixture.initialize_calls == ["lease", "target"] and len(fixture.children) == 2
    assert fixture.queue.closed and fixture.queue.cancelled
    assert all(report[name] is None for name in ("source_commit", "source_manifest_sha256", "governed_unknown_count",
        "governed_reservations", "workload_rpo", "physical_database_failover_rto"))
    assert len(fixture.verifications) == 1
    assert fixture.child_specs[0]["operation_id"] != fixture.child_specs[1]["operation_id"]


@pytest.mark.parametrize("mode", ["missing", "unavailable", "wrong-operation", "wrong-fingerprint", "failed",
                                   "stale-epoch", "wrong-owner", "duplicate", "mismatched-receipt"])
def test_fake_driver_missing_contradictory_or_unavailable_readback_remains_unknown_no_redispatch(monkeypatch, mode):
    fixture = DriverFixture(monkeypatch)
    fixture.rows_mode = mode
    report = fixture.run()
    assert report["accepted"] is False and report["effect_observation"] == "UNKNOWN"
    assert report["failure"]["stage"] == "authoritative-effect-readback"
    assert len(fixture.children) == 2 and len(fixture.child_specs) == 2
    assert report["separate_connection_observed_effect_count"] is None


def test_fake_driver_untrusted_receipt_cannot_settle_observation(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    fixture.receipt_error = ValueError(SECRET)
    report = fixture.run()
    assert not report["accepted"] and report["effect_observation"] == "UNKNOWN"
    assert len(fixture.verifications) == 1 and len(fixture.children) == 2


@pytest.mark.parametrize("expiry_mode", ["missing", "never-expired"])
def test_fake_driver_requires_server_expiry_before_starting_replacement(monkeypatch, expiry_mode):
    fixture = DriverFixture(monkeypatch)
    fixture.expiry_mode = expiry_mode
    report = fixture.run()
    assert not report["accepted"] and len(fixture.children) == 1
    assert report["failure"]["stage"] == "authoritative-expiry"
    assert report["new_epoch"] is None


@pytest.mark.parametrize("role", ["old", "replacement"])
def test_fake_driver_start_failure_preserves_owned_child_cleanup(monkeypatch, role):
    fixture = DriverFixture(monkeypatch)
    fixture.start_failure = role
    report = fixture.run()
    assert not report["accepted"] and report["failure"]["error_type"] == "RuntimeError"
    assert len(report["process_cleanup"]) == (1 if role == "old" else 2)
    assert all(child.calls for child in fixture.children)


def test_fake_driver_abnormal_exit_cannot_pass_despite_success_messages(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    fixture.child_exit = 17
    report = fixture.run()
    assert not report["accepted"] and report["failure"]["stage"] == "owned-resource-cleanup"
    assert report["effect_observation"] == "SIGNED_SUCCEEDED_IN_CONTROLLED_DATABASE"


def test_fake_driver_queue_cleanup_exception_preserves_failure_receipt(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    fixture.cleanup_queue_error = RuntimeError(SECRET)
    report = fixture.run()
    assert not report["accepted"] and report["cleanup_errors"] == ["RuntimeError"]
    assert fixture.queue.cancelled and len(report["process_cleanup"]) == 2


def test_fake_driver_failed_resume_signal_preserves_failure_and_cleanup(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    fixture.barrier.error = RuntimeError(SECRET)
    report = fixture.run()
    assert not report["accepted"] and report["effect_observation"] == "UNKNOWN"
    assert report["failure"]["stage"] == "replacement-acquire"
    assert report["cleanup_errors"] == ["RuntimeError"] and len(report["process_cleanup"]) == 2


def test_fake_driver_initialization_failure_never_spawns_and_is_sanitized(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    def initialize_failure(dsn):
        raise ConnectionError(SECRET)
    monkeypatch.setattr(drill, "PgFencing", initialize_failure)
    report = fixture.run()
    assert not report["accepted"] and report["failure"] == dict(stage="initialization", error_type="ConnectionError")
    assert fixture.children == [] and report["process_cleanup"] == []
    assert report["workload_rpo"] is None and report["effect_observation"] == "UNKNOWN"


def test_fake_driver_late_initialization_does_not_start_a_participant(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    @contextmanager
    def late_database(*args, **kwargs):
        fixture.clock.now = 31
        yield SimpleNamespace(execute=lambda query: SimpleNamespace(fetchone=lambda: ("160013", "read committed", "5s", "10s")))
    monkeypatch.setattr(drill, "_bounded_connection", late_database)
    report = fixture.run()
    assert not report["accepted"] and report["failure"] == dict(stage="initialization", error_type="TimeoutError")
    assert fixture.children == []


def test_fake_driver_expired_observation_after_deadline_does_not_start_replacement(monkeypatch):
    fixture = DriverFixture(monkeypatch)
    original_observe = fixture.observe
    def late_observation(*args):
        result = original_observe(*args)
        fixture.clock.now = 31
        return result
    monkeypatch.setattr(drill, "_lifecycle_observe", late_observation)
    report = fixture.run()
    assert not report["accepted"] and report["failure"] == dict(stage="authoritative-expiry", error_type="TimeoutError")
    assert len(fixture.child_specs) == len(fixture.children) == 1 and report["new_epoch"] is None


def test_spawn_wrapper_queue_failure_is_not_a_success_receipt(monkeypatch):
    monkeypatch.setattr(drill, "PgFencing", lambda dsn: object())
    monkeypatch.setattr(drill, "FencedPostgresDestination", lambda dsn, sign: object())
    monkeypatch.setattr(drill, "_participating_lease_loop", lambda **kwargs: dict(state="effect-return-unknown"))
    class FullQueue:
        def put(self, *args, **kwargs):
            raise queue.Full
    with pytest.raises(queue.Full):
        drill._lifecycle_spawned_worker(DSN, bytes(range(32)), dict(owner="replacement"), Barrier(), FullQueue())


def test_spawn_wrapper_sanitizes_unexpected_loop_failure(monkeypatch):
    messages = Messages(Clock())
    monkeypatch.setattr(drill, "PgFencing", lambda dsn: object())
    monkeypatch.setattr(drill, "FencedPostgresDestination", lambda dsn, sign: object())
    def fail(**kwargs):
        raise KeyboardInterrupt(SECRET)
    monkeypatch.setattr(drill, "_participating_lease_loop", fail)
    drill._lifecycle_spawned_worker(DSN, bytes(range(32)), dict(owner="old"), Barrier(), messages)
    terminal, timeout = messages.puts[0]
    assert timeout == .25 and terminal["verdict"]["state"] == "worker-harness-error"
    assert terminal["verdict"]["error_type"] == "KeyboardInterrupt" and SECRET not in json.dumps(terminal)


@pytest.mark.parametrize("scenario,expected", [(None, "old"), ("stale-leader", "old"), ("worker-lifecycle", "new")])
def test_cli_default_contract_and_explicit_scenario_selection(monkeypatch, capsys, scenario, expected):
    monkeypatch.setenv("AGENTBRIDGE_DISPOSABLE_STALE_LEADER", "1")
    monkeypatch.setenv("AGENTBRIDGE_TEST_PG", DSN)
    if scenario is None:
        monkeypatch.delenv("AGENTBRIDGE_STALE_LEADER_SCENARIO", raising=False)
    else:
        monkeypatch.setenv("AGENTBRIDGE_STALE_LEADER_SCENARIO", scenario)
    calls = []
    def result(which, dsn):
        assert dsn == DSN
        calls.append(which)
        return dict(accepted=True, scenario=which)
    monkeypatch.setattr(drill, "run_disposable_drill", lambda dsn: result("old", dsn))
    monkeypatch.setattr(drill, "run_worker_lifecycle_drill", lambda dsn: result("new", dsn))
    drill.main()
    assert calls == [expected] and json.loads(capsys.readouterr().out)["scenario"] == expected


@pytest.mark.parametrize("opt_in,scenario", [(None, "worker-lifecycle"), ("0", "worker-lifecycle"), ("1", "promote")])
def test_cli_refuses_missing_opt_in_or_unknown_scenario_before_invocation(monkeypatch, opt_in, scenario):
    if opt_in is None:
        monkeypatch.delenv("AGENTBRIDGE_DISPOSABLE_STALE_LEADER", raising=False)
    else:
        monkeypatch.setenv("AGENTBRIDGE_DISPOSABLE_STALE_LEADER", opt_in)
    monkeypatch.setenv("AGENTBRIDGE_STALE_LEADER_SCENARIO", scenario)
    def forbidden(*args):
        pytest.fail("refused CLI reached runner")
    monkeypatch.setattr(drill, "run_disposable_drill", forbidden)
    monkeypatch.setattr(drill, "run_worker_lifecycle_drill", forbidden)
    with pytest.raises(SystemExit):
        drill.main()


def test_cli_nonpassing_new_trial_returns_nonzero_and_does_not_overwrite_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTBRIDGE_DISPOSABLE_STALE_LEADER", "1")
    monkeypatch.setenv("AGENTBRIDGE_STALE_LEADER_SCENARIO", "worker-lifecycle")
    calls = []
    def run(dsn):
        calls.append(dsn)
        return dict(accepted=False)
    monkeypatch.setattr(drill, "run_worker_lifecycle_drill", run)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("AGENTBRIDGE_STALE_LEADER_REPORT", str(receipt))
    with pytest.raises(SystemExit) as error:
        drill.main()
    assert error.value.code == 1 and json.loads(receipt.read_text()) == dict(accepted=False)
    with pytest.raises(FileExistsError):
        drill.main()
    assert json.loads(receipt.read_text()) == dict(accepted=False) and len(calls) == 1
