"""Disposable multiprocess stale-leader/destination fencing acceptance drill.

A worker pauses after preparing a signed action but before reaching the
destination. While it is isolated, its lease expires, a replacement acquires
a higher epoch and commits a different action. When the old process resumes,
the destination must reject the stale epoch before any effect is inserted.

This exercises two OS processes and independent PostgreSQL connections against
ONE authoritative writable PostgreSQL system. It does not model two writable
primaries, arbitrary SaaS APIs, a real network partition or automatic HA.

The opt-in worker-lifecycle scenario adds two bounded participating lease loops,
drain-and-expire handover and observed uncertainty without automatic effect replay.
"""
from __future__ import annotations

import json
import math
import multiprocessing
import os
import queue
import time
import uuid

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.fenced_postgres_destination import (
    DuplicateDestinationAction,
    FencedPostgresDestination,
    StaleDestinationLeader,
)
from src.governance.pg_fencing import FenceDenied, PgFencing, _bounded_connection
from src.governance.destination_receipts import verify_destination_receipt


def _delayed_worker(dsn, scope, epoch, agent_id, operation_id, fingerprint,
                    signing_key_bytes, entered, resume, results):
    """Separate process, separate DB connection; no access to parent state."""
    key = Ed25519PrivateKey.from_private_bytes(signing_key_bytes)

    def sign_after_partition(payload):
        entered.set()
        if not resume.wait(15):
            raise TimeoutError("disposable worker barrier timed out")
        return key.sign(payload)

    try:
        FencedPostgresDestination(dsn, sign=sign_after_partition).commit(
            scope=scope,
            owner="old-worker",
            epoch=epoch,
            agent_id=agent_id,
            operation_id=operation_id,
            fingerprint=fingerprint,
        )
    except StaleDestinationLeader:
        results.put("stale-fenced")
    except Exception as exc:
        results.put("unexpected-error:" + type(exc).__name__)
    else:
        results.put("UNSAFE-stale-effect-committed")


def run_disposable_drill(dsn: str) -> dict:
    if not isinstance(dsn, str) or "agentbridge_test" not in dsn:
        raise ValueError("only explicit disposable PostgreSQL test database allowed")

    stamp = uuid.uuid4().hex
    scope = "failover-" + stamp
    agent = "failover-agent-" + stamp
    old_operation = "old-worker-" + stamp
    promoted_operation = "promoted-worker-" + stamp
    fingerprint = "approved-operation-" + stamp
    key = Ed25519PrivateKey.generate()
    key_raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )

    fences = PgFencing(dsn)
    fences.initialize()
    destination = FencedPostgresDestination(dsn, sign=key.sign)
    destination.initialize()
    old_epoch = fences.acquire(scope, "old-worker", ttl_seconds=1.5)

    # 'spawn' means no process-local lock or in-memory lease can accidentally
    # satisfy this test. The child creates a fresh PostgreSQL connection.
    ctx = multiprocessing.get_context("spawn")
    entered, resume = ctx.Event(), ctx.Event()
    results = ctx.Queue()
    child = ctx.Process(
        target=_delayed_worker,
        args=(dsn, scope, old_epoch, agent, old_operation, fingerprint,
              key_raw, entered, resume, results),
        name="agentbridge-disposable-stale-leader",
    )
    child.start()
    try:
        if not entered.wait(12):
            raise AssertionError("old process never reached pre-dispatch barrier")

        # Acquire on the server-side expiry condition, not a local wall clock.
        deadline = time.monotonic() + 12
        while True:
            try:
                new_epoch = fences.acquire(
                    scope, "promoted-worker", ttl_seconds=30
                )
                break
            except FenceDenied:
                if time.monotonic() >= deadline:
                    raise AssertionError("failed to acquire a higher fencing epoch")
                time.sleep(0.08)
        if new_epoch <= old_epoch:
            raise AssertionError("fencing epoch failed to increase")
        if fences.check(scope, "old-worker", old_epoch):
            raise AssertionError("stale worker still holds authoritative lease")

        # Commit the promoted worker's operation while dropping its ACK.
        # The effect must persist but should not be executed a second time.
        try:
            destination.commit(
                scope=scope, owner="promoted-worker", epoch=new_epoch,
                agent_id=agent, operation_id=promoted_operation,
                fingerprint=fingerprint, lose_ack=True,
            )
        except TimeoutError as exc:
            if "ACK was lost" not in str(exc):
                raise
        else:
            raise AssertionError("lost acknowledgment was not injected")

        # Resume the isolated old process after the newer leader committed.
        resume.set()
        verdict = results.get(timeout=12)
        child.join(timeout=8)
        if child.exitcode != 0 or verdict != "stale-fenced":
            raise AssertionError(
                "destination did not deny old process: " + str(verdict)
            )

        try:
            fences.renew(scope, "old-worker", old_epoch, ttl_seconds=30)
        except FenceDenied:
            pass
        else:
            raise AssertionError("old leader unexpectedly renewed stale epoch")

        try:
            destination.commit(
                scope=scope, owner="promoted-worker", epoch=new_epoch,
                agent_id=agent, operation_id=promoted_operation,
                fingerprint=fingerprint,
            )
        except DuplicateDestinationAction:
            pass
        else:
            raise AssertionError("committed operation was replayed")

        # Query persisted effects over another PostgreSQL connection.
        with psycopg.connect(dsn) as verify:
            rows = verify.execute(
                "SELECT operation_id, outcome FROM public.ab_evidence_effects "
                "WHERE agent_id=%s ORDER BY operation_id", (agent,)
            ).fetchall()
        if rows != [(promoted_operation, "succeeded")]:
            raise AssertionError("stale or duplicate effect found at destination")

        return {
            "kind": "disposable-multiprocess-fenced-destination-failover",
            "old_epoch": old_epoch,
            "promoted_epoch": new_epoch,
            "process_isolation": "spawn-separate-OS-process",
            "stale_old_process_denied": True,
            "stale_lease_renewal_denied": True,
            "promoted_ack_lost_after_commit": True,
            "duplicate_execution_denied": True,
            "persisted_effect_count": len(rows),
            "accepted": True,
            "limitations": (
                "single authoritative PostgreSQL writer; not two writable "
                "primaries, a real CNI partition, customer destination or "
                "universal exactly-once guarantee"
            ),
        }
    finally:
        resume.set()
        child.join(timeout=3)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        results.close()


def _lifecycle_settings(dsn, ttl_seconds, renew_interval, window_seconds):
    """Only a caller-granted numeric-loopback disposable fixture is eligible."""
    if os.getenv("AGENTBRIDGE_ENV", "").strip().lower() in {"prod", "production"}:
        raise ValueError("worker lifecycle drill is nonproduction only")
    for value in (ttl_seconds, renew_interval, window_seconds):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("finite lifecycle bounds required")
    if not (.75 <= ttl_seconds <= 5 and .05 <= renew_interval <= ttl_seconds / 3
            and 4 * ttl_seconds <= window_seconds <= 45):
        raise ValueError("lifecycle timing outside disposable bounds")
    info = conninfo_to_dict(dsn)
    if (info.get("host") != "127.0.0.1" or info.get("hostaddr", "127.0.0.1") != "127.0.0.1"
            or info.get("dbname") != "agentbridge_test" or info.get("service")
            or not info.get("user") or not info.get("password")
            or not str(info.get("port", "")).isdigit()
            or not 1024 <= int(info["port"]) <= 65535):
        raise ValueError("explicit numeric-loopback disposable fixture required")
    # Do not inherit service files, an alternate namespace, or PG* defaults.
    return make_conninfo(host="127.0.0.1", hostaddr="127.0.0.1", port=info["port"],
                         dbname="agentbridge_test", user=info["user"], password=info["password"],
                         sslmode="disable", connect_timeout=5,
                         options="-csearch_path=public -cstatement_timeout=10000 -clock_timeout=5000")


def _participating_lease_loop(*, lease, target, role, scope, owner, operation_id,
                              agent_id, fingerprint, ttl_seconds, renew_interval,
                              window_seconds, resume, emit, clock=time.monotonic,
                              sleep=time.sleep):
    """Finite worker participation; only a known acquisition refusal may retry.

    Inject lease/target/clock/event fakes in the offline harness. This does not
    authorize an effect: every actual call still passes the existing target gate.
    """
    if role not in {"old", "replacement"}:
        raise ValueError("known participating-worker role required")
    counts = dict(acquire_attempts=0, acquire_refusals=0, renew_acknowledgments=0,
                  lease_response_unknown=0, destination_attempts=0,
                  effect_return_unknown=0, stale_renew_refusals=0, stale_effect_refusals=0)
    deadline = clock() + window_seconds

    def finish(state, phase, error=None):
        return dict(state=state, phase=phase, dispatch_stopped=True, counts=dict(counts),
                    error_type=None if error is None else type(error).__name__)

    def event(kind, **values):
        emit(dict(kind=kind, owner=owner, **values))

    epoch = None
    for _ in range(64):
        if clock() >= deadline:
            return finish("timeout", "acquire")
        counts["acquire_attempts"] += 1
        try:
            epoch = lease.acquire(scope, owner, ttl_seconds=ttl_seconds)
        except FenceDenied:
            counts["acquire_refusals"] += 1
            event("acquire-refused")
            sleep(min(renew_interval, max(0, deadline-clock())))
            continue
        except Exception as exc:
            counts["lease_response_unknown"] += 1
            return finish("lease-response-unknown", "acquire", exc)
        if type(epoch) is not int or epoch < 1:
            return finish("invalid-lease-response", "acquire")
        if clock() >= deadline:
            return finish("timeout", "post-acquire")
        event("lease-acquired", epoch=epoch)
        break
    else:
        return finish("attempt-bound", "acquire")

    if role == "old":
        for _ in range(2):
            sleep(min(renew_interval, max(0, deadline-clock())))
            if clock() >= deadline:
                return finish("timeout", "renew")
            try:
                renewed = lease.renew(scope, owner, epoch, ttl_seconds=ttl_seconds)
            except FenceDenied as exc:
                return finish("lease-refused", "renew", exc)
            except Exception as exc:
                counts["lease_response_unknown"] += 1
                return finish("lease-response-unknown", "renew", exc)
            if type(renewed) is not int or renewed != epoch:
                return finish("invalid-lease-response", "renew")
            counts["renew_acknowledgments"] += 1
            event("lease-renewed", epoch=epoch)
        # Stop renewal deliberately. The parent observes the actual DB expiry
        # before starting the contender; no lease delete/reset/release exists.
        event("renewal-drained", epoch=epoch)
        if not resume.wait(max(0, deadline-clock())):
            return finish("timeout", "drained")
        if clock() >= deadline:
            return finish("timeout", "resume")
        # Explicit stale-gate probes are distinct operations, never recovery
        # retries of the replacement's uncertain consequential operation.
        try:
            lease.renew(scope, owner, epoch, ttl_seconds=ttl_seconds)
        except FenceDenied:
            counts["stale_renew_refusals"] += 1
            event("stale-renewal-refused", epoch=epoch)
        except Exception as exc:
            counts["lease_response_unknown"] += 1
            return finish("lease-response-unknown", "stale-renew-probe", exc)
        else:
            return finish("unsafe-stale-renewal", "stale-renew-probe")
        if clock() >= deadline:
            return finish("timeout", "stale-effect-probe")
        counts["destination_attempts"] += 1
        try:
            target.commit(scope=scope, owner=owner, epoch=epoch, agent_id=agent_id,
                          operation_id=operation_id, fingerprint=fingerprint)
        except StaleDestinationLeader:
            counts["stale_effect_refusals"] += 1
            event("stale-effect-refused", operation_id=operation_id)
        except Exception as exc:
            counts["effect_return_unknown"] += 1
            return finish("effect-return-unknown", "stale-effect-probe", exc)
        else:
            return finish("unsafe-stale-effect", "stale-effect-probe")
        return finish("stale-probes-complete", "stopped")

    if clock() >= deadline:
        return finish("timeout", "one-effect-attempt")
    counts["destination_attempts"] += 1
    try:
        target.commit(scope=scope, owner=owner, epoch=epoch, agent_id=agent_id,
                      operation_id=operation_id, fingerprint=fingerprint, lose_ack=True)
    except (StaleDestinationLeader, DuplicateDestinationAction) as exc:
        return finish("destination-refused", "one-effect-attempt", exc)
    except Exception as exc:
        counts["effect_return_unknown"] += 1
        event("effect-return-unknown", operation_id=operation_id, error_type=type(exc).__name__)
        return finish("effect-return-unknown", "stopped", exc)
    event("effect-acknowledged", operation_id=operation_id)
    return finish("effect-acknowledged", "stopped")


def _lifecycle_spawned_worker(dsn, private_key, spec, resume, results):
    """Spawn entry point; no source or credentials appear in result messages."""
    def emit(event):
        results.put(event, timeout=.25)
    try:
        key = Ed25519PrivateKey.from_private_bytes(private_key)
        verdict = _participating_lease_loop(
            lease=PgFencing(dsn), target=FencedPostgresDestination(dsn, sign=key.sign),
            resume=resume, emit=emit, **spec)
    except BaseException as exc:
        verdict = dict(state="worker-harness-error", phase="worker", dispatch_stopped=True,
                       counts={}, error_type=type(exc).__name__)
    results.put(dict(kind="terminal", owner=spec["owner"], verdict=verdict), timeout=.25)


def _receive_lifecycle_events(results, events, predicate, deadline, began, clock=None):
    clock = time.monotonic if clock is None else clock
    while not predicate(events):
        remaining = deadline-clock()
        if remaining <= 0 or len(events) >= 128:
            raise TimeoutError("bounded worker observation incomplete")
        try:
            event = results.get(timeout=min(.1, remaining))
        except queue.Empty:
            continue
        if (not isinstance(event, dict) or not isinstance(event.get("kind"), str)
                or len(json.dumps(event, allow_nan=False)) > 4096):
            raise ValueError("invalid bounded worker message")
        event = dict(event, parent_observed_seconds=clock()-began)
        events.append(event)
        if clock() >= deadline:
            raise TimeoutError("worker message arrived outside observation window")
        if event["kind"] == "terminal" and event["verdict"]["state"] not in {
                "stale-probes-complete", "effect-return-unknown"}:
            raise RuntimeError("participating worker stopped without the required observations")


def _lifecycle_observe(dsn, scope, agent_id):
    with _bounded_connection(dsn, autocommit=True, row_factory=dict_row) as conn:
        state = conn.execute(
            "SELECT owner,epoch,expires::text AS expires,expires<=clock_timestamp() AS expired,"
            "clock_timestamp()::text AS database_clock FROM public.agentbridge_fences WHERE scope=%s",
            (scope,)).fetchone()
        rows = conn.execute(
            "SELECT operation_id,fingerprint,outcome,external_reference,receipt_json "
            "FROM public.ab_evidence_effects WHERE agent_id=%s ORDER BY operation_id LIMIT 4",
            (agent_id,)).fetchall()
    return state, rows


def _cleanup_lifecycle_children(children):
    observations = []
    for child in children:
        row = dict(name=None, exitcode=None, terminate_requested=False,
                   kill_requested=False, still_alive=None, error_types=[])
        def action(callback):
            try:
                return callback()
            except BaseException as exc:
                row["error_types"].append(type(exc).__name__)
                return None
        row["name"] = action(lambda: child.name)
        action(lambda: child.join(timeout=2))
        alive = action(child.is_alive)
        if alive is True:
            row["terminate_requested"] = True
            action(child.terminate)
            action(lambda: child.join(timeout=3))
        alive = action(child.is_alive)
        if alive is True:
            row["kill_requested"] = True
            action(child.kill)
            action(lambda: child.join(timeout=2))
        row["still_alive"] = action(child.is_alive)
        row["exitcode"] = action(lambda: child.exitcode)
        observations.append(row)
    return observations


def run_worker_lifecycle_drill(dsn, *, ttl_seconds=3, renew_interval=.25, window_seconds=30):
    """One finite two-process drain/expiry trial, not a physical HA service.

    Return complete sanitized failure observations. A separate caller must bound
    actual network blackholes: server SQL settings are not a client receive cap.
    """
    dsn = _lifecycle_settings(dsn, ttl_seconds, renew_interval, window_seconds)
    stamp = uuid.uuid4().hex
    scope, agent_id = "lifecycle-"+stamp, "lifecycle-agent-"+stamp
    old_owner, new_owner = "old-worker", "replacement-worker"
    old_operation, new_operation = "stale-probe-"+stamp, "replacement-"+stamp
    fingerprint = "lifecycle-approved-"+stamp
    report = dict(kind="single-authority-participating-worker-lifecycle", trial_id=stamp,
                  accepted=False, stage="initialization", events=[], server_observations=[],
                  effect_observation="UNKNOWN", process_cleanup=[], cleanup_errors=[], failure=None,
                  old_epoch=None, new_epoch=None, source_commit=None, source_manifest_sha256=None,
                  drain_observed_seconds=None, drain_to_higher_epoch_seconds=None,
                  drain_to_observed_replacement_effect_seconds=None,
                  separate_connection_observed_effect_count=None, stale_effect_count=None,
                  ttl_seconds=ttl_seconds, renew_interval=renew_interval,
                  observation_window_seconds=window_seconds,
                  governed_unknown_count=None, governed_reservations=None, workload_rpo=None,
                  physical_database_failover_rto=None,
                  limitations="one owned PostgreSQL writer; no governed-task/accounting integration, "
                              "physical promotion, independent custody, real network partition, "
                              "hard client-network deadline or production acceptance")
    began = time.monotonic()
    deadline = began+window_seconds
    children, resume, results = [], None, None
    try:
        key = Ed25519PrivateKey.generate()
        key_raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption())
        public_hex = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        # Initialize the existing shared schema once, before any participant.
        PgFencing(dsn).initialize()
        FencedPostgresDestination(dsn, sign=key.sign).initialize()
        with _bounded_connection(dsn, autocommit=True) as conn:
            report["database"] = conn.execute(
                "SELECT current_setting('server_version_num'),current_setting('transaction_isolation'),"
                "current_setting('lock_timeout'),current_setting('statement_timeout')").fetchone()
        if time.monotonic() >= deadline:
            raise TimeoutError("initialization exceeded observation window")
        ctx = multiprocessing.get_context("spawn")
        resume, results = ctx.Event(), ctx.Queue(maxsize=128)
        common = dict(scope=scope, agent_id=agent_id, fingerprint=fingerprint,
                      ttl_seconds=ttl_seconds, renew_interval=renew_interval,
                      window_seconds=window_seconds)
        old = ctx.Process(target=_lifecycle_spawned_worker,
                          args=(dsn, key_raw, dict(common, role="old", owner=old_owner,
                                                 operation_id=old_operation), resume, results),
                          name="agentbridge-owned-lifecycle-old")
        children.append(old)
        old.start()
        report["stage"] = "old-renew-and-drain"
        _receive_lifecycle_events(results, report["events"],
                                  lambda rows: any(r["kind"] == "renewal-drained" and r["owner"] == old_owner for r in rows),
                                  deadline, began)
        trigger = time.monotonic()-began
        report["drain_observed_seconds"] = trigger
        old_epoch = next(r["epoch"] for r in report["events"]
                         if r["kind"] == "renewal-drained" and r["owner"] == old_owner)
        report["stage"] = "authoritative-expiry"
        for _ in range(128):
            if time.monotonic() >= deadline:
                raise TimeoutError("authoritative expiry not observed")
            state, rows = _lifecycle_observe(dsn, scope, agent_id)
            if not state or state["owner"] != old_owner or state["epoch"] != old_epoch or rows:
                raise RuntimeError("authoritative old-worker state contradicted the trial")
            report["server_observations"].append(dict(state, parent_observed_seconds=time.monotonic()-began))
            if time.monotonic() >= deadline:
                raise TimeoutError("authoritative expiry response exceeded observation window")
            if state["expired"] is True:
                break
            time.sleep(.05)
        else:
            raise TimeoutError("bounded expiry observations exhausted")
        if time.monotonic() >= deadline:
            raise TimeoutError("replacement start observation window exhausted")
        replacement = ctx.Process(target=_lifecycle_spawned_worker,
                                  args=(dsn, key_raw, dict(common, role="replacement", owner=new_owner,
                                                         operation_id=new_operation), resume, results),
                                  name="agentbridge-owned-lifecycle-replacement")
        children.append(replacement)
        replacement.start()
        report["stage"] = "replacement-acquire"
        _receive_lifecycle_events(results, report["events"],
                                  lambda rows: any(r["kind"] == "lease-acquired" and r["owner"] == new_owner for r in rows),
                                  deadline, began)
        acquired = next(r for r in report["events"] if r["kind"] == "lease-acquired" and r["owner"] == new_owner)
        if acquired["epoch"] <= old_epoch:
            raise RuntimeError("replacement epoch did not increase")
        report["old_epoch"], report["new_epoch"] = old_epoch, acquired["epoch"]
        report["drain_to_higher_epoch_seconds"] = acquired["parent_observed_seconds"]-trigger
        resume.set()
        report["stage"] = "worker-terminal-observations"
        _receive_lifecycle_events(results, report["events"],
                                  lambda rows: len([r for r in rows if r["kind"] == "terminal"]) == 2,
                                  deadline, began)
        terminals = {r["owner"]: r["verdict"] for r in report["events"] if r["kind"] == "terminal"}
        if (terminals[old_owner]["state"] != "stale-probes-complete"
                or terminals[old_owner]["counts"]["renew_acknowledgments"] != 2
                or terminals[new_owner]["state"] != "effect-return-unknown"
                or terminals[new_owner]["counts"]["destination_attempts"] != 1):
            raise RuntimeError("worker lifecycle observations incomplete")
        report["stage"] = "authoritative-effect-readback"
        if time.monotonic() >= deadline:
            raise TimeoutError("effect readback observation window exhausted")
        state, rows = _lifecycle_observe(dsn, scope, agent_id)
        if (not state or state["owner"] != new_owner or state["epoch"] != acquired["epoch"]
                or len(rows) != 1 or rows[0]["operation_id"] != new_operation
                or rows[0]["fingerprint"] != fingerprint or rows[0]["outcome"] != "succeeded"):
            raise RuntimeError("authoritative replacement effect unresolved or contradictory")
        row = rows[0]
        receipt_digest = verify_destination_receipt(
            row["receipt_json"], agent_id=agent_id, operation_id=new_operation,
            fingerprint=fingerprint, trusted_public_key_hex=public_hex)
        if row["receipt_json"]["outcome"] != row["outcome"] or row["receipt_json"]["external_reference"] != row["external_reference"]:
            raise RuntimeError("signed receipt contradicts authoritative row")
        report.update(effect_observation="SIGNED_SUCCEEDED_IN_CONTROLLED_DATABASE",
                      separate_connection_observed_effect_count=1, stale_effect_count=0,
                      observed_receipt_sha256=receipt_digest,
                      drain_to_observed_replacement_effect_seconds=time.monotonic()-began-trigger,
                      retained_scope=scope, retained_agent_id=agent_id,
                      retained_operation_id=new_operation)
        report["stage"] = "observed"
        if time.monotonic() >= deadline:
            raise TimeoutError("effect readback exceeded observation window")
    except BaseException as exc:
        report["failure"] = dict(stage=report["stage"], error_type=type(exc).__name__)
    finally:
        def cleanup_action(callback):
            try:
                callback()
            except BaseException as exc:
                report["cleanup_errors"].append(type(exc).__name__)
        if resume is not None:
            cleanup_action(resume.set)
        report["process_cleanup"] = _cleanup_lifecycle_children(children)
        if results is not None:
            cleanup_action(results.close)
            cleanup_action(results.cancel_join_thread)
        report["elapsed_seconds"] = time.monotonic()-began
        clean = (not report["cleanup_errors"] and len(report["process_cleanup"]) == 2
                 and all(r["still_alive"] is False and r["exitcode"] == 0
                         and not r["error_types"]
                         and not r["terminate_requested"] and not r["kill_requested"]
                         for r in report["process_cleanup"]))
        if report["failure"] is None and not clean:
            report["failure"] = dict(stage="owned-resource-cleanup", error_type="IncompleteCleanup")
        report["accepted"] = (report["failure"] is None and report["stage"] == "observed"
                              and clean)
    return report


def main():
    if os.getenv("AGENTBRIDGE_DISPOSABLE_STALE_LEADER") != "1":
        raise SystemExit("explicit disposable fault-drill opt-in required")
    scenario = os.getenv("AGENTBRIDGE_STALE_LEADER_SCENARIO", "stale-leader")
    if scenario not in {"stale-leader", "worker-lifecycle"}:
        raise SystemExit("known disposable stale-leader scenario required")
    run = run_disposable_drill if scenario == "stale-leader" else run_worker_lifecycle_drill
    output = os.getenv("AGENTBRIDGE_STALE_LEADER_REPORT")
    if output and scenario == "worker-lifecycle":
        # Reserve this receipt before any effect attempt, never after dispatch.
        with open(output, "x", encoding="utf-8") as destination:
            report = run(os.getenv("AGENTBRIDGE_TEST_PG", ""))
            json.dump(report, destination, indent=2, sort_keys=True)
    else:
        report = run(os.getenv("AGENTBRIDGE_TEST_PG", ""))
        if output:
            with open(output, "w", encoding="utf-8") as destination:
                json.dump(report, destination, indent=2, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True))
    if scenario == "worker-lifecycle" and not report["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
