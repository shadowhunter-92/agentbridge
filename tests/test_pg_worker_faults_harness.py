"""Offline active-leader and committed-method return-loss controls.

Mocks exercise control flow only: no processes, PostgreSQL or network traffic.
Actual operated fault trials require a separately reviewed bounded runner.
"""
from types import SimpleNamespace
import copy
import json

import pytest

from tools import drill_pg_stale_leader as drill
from tests.test_pg_worker_lifecycle_harness import (
    DSN, SECRET, Barrier, Child, Clock, DriverFixture, Lease, Messages, Target,
    offline_boundary as offline_boundary, resolve, run_worker,
)


@pytest.mark.parametrize("phase", ["acquire", "renew"])
def test_committed_method_reply_loss_stops_worker_without_retry_or_effect(phase):
    underlying, injected = Lease(), []
    lease = drill._CommittedLeaseReplyLoss(underlying, phase, injected.append)
    verdict, _, target, _ = run_worker("old", lease=lease)
    assert verdict["state"] == "lease-response-unknown" and verdict["phase"] == phase
    assert verdict["error_type"] == "ControlledLeaseReplyLoss"
    assert verdict["counts"]["lease_response_unknown"] == 1
    assert verdict["counts"]["destination_attempts"] == 0 and target.calls == []
    assert [row[0] for row in underlying.calls] == (["acquire"] if phase == "acquire" else ["acquire", "renew"])
    assert injected == [phase] and lease.used
    before = copy.deepcopy(underlying.calls)
    with pytest.raises(RuntimeError, match="cannot retry"):
        lease.acquire("same-scope", "same-owner", ttl_seconds=3)
    assert underlying.calls == before


@pytest.mark.parametrize("phase", ["acquire", "renew"])
@pytest.mark.parametrize("failure", [TimeoutError(SECRET), drill.FenceDenied(SECRET)])
def test_method_failure_is_not_reported_as_injected_committed_reply_loss(phase, failure):
    underlying = Lease(acquire=(failure,) if phase == "acquire" else (1,), renew=(failure,))
    injected = []
    lease = drill._CommittedLeaseReplyLoss(underlying, phase, injected.append)
    call = lease.acquire if phase == "acquire" else lease.renew
    with pytest.raises(type(failure)):
        call("scope", "owner")
    assert injected == [] and not lease.used


@pytest.mark.parametrize("value", [True, False, None, 0, -1, 1.0, "1"])
def test_invalid_method_token_is_not_promoted_into_injection_evidence(value):
    underlying, injected = Lease(acquire=(value,)), []
    lease = drill._CommittedLeaseReplyLoss(underlying, "acquire", injected.append)
    result, _, target, _ = run_worker("old", lease=lease)
    assert result["state"] == "invalid-lease-response"
    assert target.calls == [] and injected == [] and not lease.used


@pytest.mark.parametrize("phase", [None, "effect", "ACQUIRE", ""])
def test_unknown_reply_loss_phase_refuses_before_method_call(phase):
    underlying = Lease()
    with pytest.raises(ValueError):
        drill._CommittedLeaseReplyLoss(underlying, phase, lambda _: None)
    assert underlying.calls == []


def test_active_old_worker_keeps_renewing_without_cooperative_drain_or_effect():
    result, lease, target, events = run_worker(
        "old", lease=Lease(renew=(1,) * 70), active_until_stopped=True, window_seconds=1)
    assert result["state"] == "timeout" and result["phase"] == "active-renew"
    kinds = [row["kind"] for row in events]
    ready = kinds.index("active-leader-ready")
    assert kinds[:ready].count("lease-renewed") == 2
    assert "lease-renewed" in kinds[ready+1:]
    assert "renewal-drained" not in kinds and target.calls == []
    assert result["counts"]["renew_acknowledgments"] > 2


@pytest.mark.parametrize("failure,expected", [
    (TimeoutError(SECRET), "lease-response-unknown"),
    (drill.FenceDenied(SECRET), "lease-refused"),
    (2, "invalid-lease-response"),
])
def test_active_leader_stops_on_unknown_refusal_or_changed_epoch(failure, expected):
    result, lease, target, events = run_worker(
        "old", lease=Lease(renew=(1, 1, failure)), active_until_stopped=True)
    assert result["state"] == expected and result["phase"] == "active-renew"
    assert [row[0] for row in lease.calls] == ["acquire", "renew", "renew", "renew"]
    assert target.calls == [] and not any(row["kind"] == "renewal-drained" for row in events)


@pytest.mark.parametrize("mode,role", [(True, "replacement"), (None, "old"), (1, "old"), ("yes", "old")])
def test_active_mode_refuses_invalid_role_or_nonboolean(mode, role):
    with pytest.raises(ValueError):
        run_worker(role, active_until_stopped=mode)


@pytest.mark.parametrize("exitcode", [0, -15, 137])
def test_owned_stop_uses_liveness_and_join_not_exitcode_sign(exitcode):
    child = Child("agentbridge-owned-lifecycle-old", alive=True)
    child.pid = 123
    original = child.terminate
    def stop():
        original()
        child.exitcode = exitcode
    child.terminate = stop
    result = drill._stop_owned_lifecycle_leader(child, 10, Clock())
    assert result["accepted"] and result["alive_before"] is True and result["alive_after"] is False
    assert result["pid"] == 123 and result["exitcode"] == exitcode
    assert child.calls == [("is_alive",), ("terminate",), ("join", 2), ("is_alive",)]


@pytest.mark.parametrize("name,pid,alive", [
    ("foreign", 123, True), ("agentbridge-owned-lifecycle-old", True, True),
    ("agentbridge-owned-lifecycle-old", 0, True), ("agentbridge-owned-lifecycle-old", 123, False),
])
def test_owned_stop_refuses_wrong_identity_or_not_live_without_signaling(name, pid, alive):
    child = Child(name, alive=alive)
    child.pid = pid
    result = drill._stop_owned_lifecycle_leader(child, 10, Clock())
    assert not result["accepted"] and not result["terminate_requested"]
    assert not any(call[0] in {"terminate", "kill"} for call in child.calls)


@pytest.mark.parametrize("failure_stage", ["terminate", "join", "is_alive"])
def test_owned_stop_error_is_sanitized_and_never_claims_termination(failure_stage):
    child = Child("agentbridge-owned-lifecycle-old", alive=True)
    child.pid = 123
    child.errors[failure_stage] = OSError(SECRET)
    result = drill._stop_owned_lifecycle_leader(child, 10, Clock())
    assert not result["accepted"] and result["error_type"] == "OSError"
    assert SECRET not in json.dumps(result)


def test_owned_stop_deadline_or_surviving_process_cannot_pass():
    child = Child("agentbridge-owned-lifecycle-old", alive=True, terminate_stops=False)
    child.pid = 123
    assert not drill._stop_owned_lifecycle_leader(child, 10, Clock())["accepted"]
    child.calls.clear()
    assert not drill._stop_owned_lifecycle_leader(child, 0, Clock())["terminate_requested"]


class FaultDriver(DriverFixture):
    """Extend existing offline driver without replacing real resource guards."""
    def __init__(self, monkeypatch, fault):
        super().__init__(monkeypatch)
        self.fault, self.queues, self.reply_mode = fault, [], "valid"
        self.ready_kind, self.observed_renewals = "active-leader-ready", 2
        self.stop_stops, self.stop_error = True, None
        self.replacement_attempts = 1
        self.stale_renew = drill.FenceDenied("expired")
        self.stale_effect = drill.StaleDestinationLeader("expired")
        self.stale_calls, self.leader_stopped = [], False

    def make_queue(self, maxsize):
        assert maxsize == 128
        own = Messages(self.clock)
        self.queues.append(own)
        if self.queue is None:
            self.queue = own
        return own

    def initializer(self, name):
        def renew(*args, **kwargs):
            self.stale_calls.append(("renew", args, kwargs))
            return resolve(self.stale_renew)
        def commit(**kwargs):
            self.stale_calls.append(("commit", (), kwargs))
            return resolve(self.stale_effect)
        return SimpleNamespace(initialize=lambda: self.initialize_calls.append(name), renew=renew, commit=commit)

    def process(self, *, target, args, name):
        assert target is drill._lifecycle_spawned_worker
        spec, own_queue = args[2], args[4]
        self.child_specs.append(spec)
        child = Child(name, terminate_stops=self.stop_stops)
        child.pid = 100 + len(self.children)
        original_stop = child.terminate
        def stop():
            self.leader_stopped = True
            original_stop()
        child.terminate = stop
        if self.stop_error:
            child.errors["terminate"] = self.stop_error

        def start():
            if self.start_failure == spec["role"]:
                raise RuntimeError(SECRET)
            if spec["role"] == "replacement":
                own_queue.values.extend([
                    dict(kind="lease-acquired", owner=spec["owner"], epoch=2),
                    dict(kind="terminal", owner=spec["owner"],
                         verdict=dict(state="effect-return-unknown", counts=dict(destination_attempts=self.replacement_attempts)))])
            elif self.fault == "forced-stop":
                child.alive, child.exitcode = True, None
                own_queue.values.extend([dict(kind="lease-acquired", owner=spec["owner"], epoch=1)]
                    + [dict(kind="lease-renewed", owner=spec["owner"], epoch=1)] * self.observed_renewals
                    + [dict(kind=self.ready_kind, owner=spec["owner"], epoch=1)])
                original_get = own_queue.get
                def old_get(timeout):
                    assert not self.leader_stopped, "stopped old-worker channel was reused"
                    return original_get(timeout)
                own_queue.get = old_get
            else:
                phase = spec["lease_reply_loss"]
                marker = dict(kind="committed-lease-reply-withheld", owner=spec["owner"], phase=phase)
                verdict = dict(state="lease-response-unknown", phase=phase,
                    dispatch_stopped=True, error_type="ControlledLeaseReplyLoss",
                    counts=dict(acquire_attempts=1, lease_response_unknown=1,
                                renew_acknowledgments=0, destination_attempts=0))
                if self.reply_mode == "wrong-phase": marker["phase"] = "other"
                if self.reply_mode == "wrong-owner": marker["owner"] = "foreign"
                if self.reply_mode == "ordinary-error": verdict["error_type"] = "TimeoutError"
                if self.reply_mode == "retry": verdict["counts"]["acquire_attempts"] = 2
                if self.reply_mode == "effect": verdict["counts"]["destination_attempts"] = 1
                if self.reply_mode == "boolean-count": verdict["counts"]["destination_attempts"] = False
                if self.reply_mode != "missing-marker":
                    own_queue.values.append(marker)
                own_queue.values.append(dict(kind="terminal", owner=spec["owner"], verdict=verdict))
        child.start = start
        self.children.append(child)
        return child

    def observe(self, dsn, scope, agent):
        if self.fault not in {"acquire-reply-loss", "renew-reply-loss"}:
            return super().observe(dsn, scope, agent)
        self.observe_calls.append((scope, agent))
        state = dict(owner="old-worker", epoch=1, expired=False, expires="db-time", database_clock="db-time")
        if self.rows_mode == "missing": return None, []
        if self.rows_mode == "wrong-owner": state["owner"] = "foreign"
        if self.rows_mode == "bad-epoch": state["epoch"] = True
        return state, ([{"unexpected": "effect"}] if self.rows_mode == "effect" else [])

    def run(self):
        result = drill.run_worker_lifecycle_drill(DSN, fault=self.fault)
        assert SECRET not in json.dumps(result) and "fake-only" not in json.dumps(result)
        return result


def test_forced_active_leader_parent_uses_separate_queue_then_expiry_stale_gates_and_one_successor(monkeypatch):
    fixture = FaultDriver(monkeypatch, "forced-stop")
    report = fixture.run()
    assert report["accepted"] and report["forced_stop"]["accepted"]
    assert fixture.child_specs[0]["active_until_stopped"] is True
    assert report["drain_observed_seconds"] is None and report["drain_to_higher_epoch_seconds"] is None
    assert report["forced_stop_to_higher_epoch_seconds"] is not None
    assert report["separate_connection_observed_effect_count"] == 1 and report["stale_effect_count"] == 0
    assert len(fixture.queues) == 2 and fixture.queues[0] is not fixture.queues[1]
    assert all(q.closed and q.cancelled for q in fixture.queues)
    assert len(fixture.children) == 2 and [c[0] for c in fixture.stale_calls] == ["renew", "commit"]
    assert fixture.stale_calls[1][2]["operation_id"] != fixture.child_specs[1]["operation_id"]


@pytest.mark.parametrize("renewals,kind", [(1, "active-leader-ready"), (2, "renewal-drained")])
def test_forced_case_requires_active_ready_and_two_renewals_before_stop(monkeypatch, renewals, kind):
    fixture = FaultDriver(monkeypatch, "forced-stop")
    fixture.observed_renewals, fixture.ready_kind = renewals, kind
    report = fixture.run()
    assert not report["accepted"] and report["forced_stop"] is None
    assert len(fixture.children) == 1 and fixture.observe_calls == []


@pytest.mark.parametrize("fault", ["survives", "signal-error"])
def test_unverified_active_leader_stop_never_starts_successor(monkeypatch, fault):
    fixture = FaultDriver(monkeypatch, "forced-stop")
    if fault == "survives": fixture.stop_stops = False
    else: fixture.stop_error = OSError(SECRET)
    report = fixture.run()
    assert not report["accepted"] and not report["forced_stop"]["accepted"]
    assert len(fixture.children) == 1 and fixture.observe_calls == []
    assert report["effect_observation"] == "UNKNOWN"


@pytest.mark.parametrize("where,result", [
    ("renew", 1), ("renew", TimeoutError(SECRET)),
    ("effect", None), ("effect", TimeoutError(SECRET)),
])
def test_forced_case_requires_precise_stale_gate_refusals_without_retry(monkeypatch, where, result):
    fixture = FaultDriver(monkeypatch, "forced-stop")
    if where == "renew": fixture.stale_renew = result
    else: fixture.stale_effect = result
    report = fixture.run()
    assert not report["accepted"] and report["effect_observation"] == "UNKNOWN"
    assert len(fixture.children) == 2
    assert len(fixture.stale_calls) == (1 if where == "renew" else 2)


@pytest.mark.parametrize("phase", ["acquire", "renew"])
def test_parent_accepts_only_stopped_reply_unknown_and_recorded_lease_with_no_effect(monkeypatch, phase):
    fixture = FaultDriver(monkeypatch, phase+"-reply-loss")
    report = fixture.run()
    assert report["accepted"] and len(fixture.children) == 1 and len(fixture.queues) == 1
    assert report["lease_reply_observation"] == "RECORDED_LEASE_WITH_WORKER_REPLY_UNKNOWN"
    assert report["effect_observation"] == "UNKNOWN" and report["separate_connection_observed_effect_count"] == 0
    assert report["new_epoch"] is None and fixture.stale_calls == []
    assert fixture.queues[0].closed and fixture.queues[0].cancelled


@pytest.mark.parametrize("mode", ["wrong-phase", "wrong-owner", "ordinary-error", "retry", "effect", "boolean-count", "missing-marker"])
def test_parent_refuses_incomplete_or_unsafe_reply_loss_messages_before_readback(monkeypatch, mode):
    fixture = FaultDriver(monkeypatch, "acquire-reply-loss")
    fixture.reply_mode = mode
    report = fixture.run()
    assert not report["accepted"] and report["effect_observation"] == "UNKNOWN"
    assert fixture.observe_calls == [] and len(fixture.children) == 1


@pytest.mark.parametrize("mode", ["missing", "wrong-owner", "bad-epoch", "effect"])
def test_reply_loss_missing_or_contradictory_authority_cannot_pass_or_dispatch(monkeypatch, mode):
    fixture = FaultDriver(monkeypatch, "renew-reply-loss")
    fixture.rows_mode = mode
    report = fixture.run()
    assert not report["accepted"] and report["effect_observation"] == "UNKNOWN"
    assert len(fixture.children) == 1 and len(fixture.observe_calls) == 1
    assert report["lease_reply_observation"] is None


@pytest.mark.parametrize("scenario,fault", [
    ("worker-forced-stop", "forced-stop"),
    ("lease-acquire-reply-loss", "acquire-reply-loss"),
    ("lease-renew-reply-loss", "renew-reply-loss"),
])
def test_explicit_fault_cli_reserves_once_and_refuses_overwrite(monkeypatch, tmp_path, scenario, fault):
    monkeypatch.setenv("AGENTBRIDGE_DISPOSABLE_STALE_LEADER", "1")
    monkeypatch.setenv("AGENTBRIDGE_STALE_LEADER_SCENARIO", scenario)
    receipt = tmp_path/"fault.json"
    monkeypatch.setenv("AGENTBRIDGE_STALE_LEADER_REPORT", str(receipt))
    calls = []
    def run(dsn, *, fault):
        calls.append((dsn, fault))
        return {"accepted": False}
    monkeypatch.setattr(drill, "run_worker_lifecycle_drill", run)
    with pytest.raises(SystemExit) as error:
        drill.main()
    assert error.value.code == 1 and calls == [("", fault)]
    with pytest.raises(FileExistsError):
        drill.main()
    assert calls == [("", fault)] and json.loads(receipt.read_text()) == {"accepted": False}


@pytest.mark.parametrize("fault", ["network-partition", True, "FORCED-STOP"])
def test_unknown_fault_refuses_before_initialization_or_process_creation(fault):
    with pytest.raises(ValueError):
        drill.run_worker_lifecycle_drill(DSN, fault=fault)


@pytest.mark.parametrize("fault", ["forced-stop", "acquire-reply-loss", "renew-reply-loss"])
@pytest.mark.parametrize("environment", ["prod", "production", " Production "])
def test_each_fault_refuses_production_before_any_resource(monkeypatch, fault, environment):
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    with pytest.raises(ValueError):
        drill.run_worker_lifecycle_drill(DSN, fault=fault)


def test_active_renewal_has_attempt_bound_even_with_nonadvancing_clock():
    clock = Clock()
    clock.sleep = lambda _: None
    result, lease, target, _ = run_worker(
        "old", clock=clock, lease=Lease(renew=(1,) * 70), active_until_stopped=True)
    assert result["state"] == "attempt-bound" and result["phase"] == "active-renew"
    assert len(lease.calls) == 67 and target.calls == []


def test_stop_that_returns_after_deadline_is_not_accepted():
    child = Child("agentbridge-owned-lifecycle-old", alive=True)
    child.pid = 123
    moments = iter((0, 11))
    result = drill._stop_owned_lifecycle_leader(child, 10, lambda: next(moments))
    assert not result["accepted"] and result["terminate_requested"]
    assert result["error_type"] == "TimeoutError"


@pytest.mark.parametrize("expiry", ["missing", "never-expired"])
def test_stopped_leader_still_requires_authoritative_expiry_before_successor(monkeypatch, expiry):
    fixture = FaultDriver(monkeypatch, "forced-stop")
    fixture.expiry_mode = expiry
    result = fixture.run()
    assert not result["accepted"] and result["forced_stop"]["accepted"]
    assert len(fixture.children) == 1 and fixture.stale_calls == []
    assert result["effect_observation"] == "UNKNOWN"


@pytest.mark.parametrize("attempts", [0, 2, True, 1.0])
def test_successor_terminal_cannot_hide_replay_or_untyped_counts(monkeypatch, attempts):
    fixture = FaultDriver(monkeypatch, "forced-stop")
    fixture.replacement_attempts = attempts
    result = fixture.run()
    assert not result["accepted"] and len(fixture.children) == 2
    assert result["effect_observation"] == "UNKNOWN"


@pytest.mark.parametrize("role", ["old", "replacement"])
def test_fault_start_failure_preserves_owned_cleanup_and_uncertainty(monkeypatch, role):
    fixture = FaultDriver(monkeypatch, "forced-stop")
    fixture.start_failure = role
    result = fixture.run()
    assert not result["accepted"] and result["effect_observation"] == "UNKNOWN"
    assert result["failure"]["error_type"] == "RuntimeError"
    assert len(result["process_cleanup"]) == (1 if role == "old" else 2)

