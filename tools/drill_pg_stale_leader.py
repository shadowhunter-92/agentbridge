"""Disposable multiprocess stale-leader/destination fencing acceptance drill.

A worker pauses after preparing a signed action but before reaching the
destination. While it is isolated, its lease expires, a replacement acquires
a higher epoch and commits a different action. When the old process resumes,
the destination must reject the stale epoch before any effect is inserted.

This exercises two OS processes and independent PostgreSQL connections against
ONE authoritative writable PostgreSQL system. It does not model two writable
primaries, arbitrary SaaS APIs, a real network partition or automatic HA.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import time
import uuid

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.fenced_postgres_destination import (
    DuplicateDestinationAction,
    FencedPostgresDestination,
    StaleDestinationLeader,
)
from src.governance.pg_fencing import FenceDenied, PgFencing


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


def main():
    if os.getenv("AGENTBRIDGE_DISPOSABLE_STALE_LEADER") != "1":
        raise SystemExit("explicit disposable fault-drill opt-in required")
    report = run_disposable_drill(os.getenv("AGENTBRIDGE_TEST_PG", ""))
    output = os.getenv("AGENTBRIDGE_STALE_LEADER_REPORT")
    if output:
        with open(output, "w", encoding="utf-8") as destination:
            json.dump(report, destination, indent=2, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
