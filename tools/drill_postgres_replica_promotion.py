"""Disposable two-container PostgreSQL streaming replica/promotion drill.

Creates separate PostgreSQL 16 Docker containers and volume, not the CI test
service. Fences the old primary BEFORE promoting; never promotes a writable
standby while the previous primary is running. Proves a durable UNKNOWN
operation cannot be replayed after promotion. Not production HA certification.
"""
from __future__ import annotations
import json
import os
import subprocess
import time
import uuid

from psycopg import connect, OperationalError
from src.governance.operation_ledger import OperationLedger, OperationConflict
from src.governance.store import PostgresStore


def run(args, *, check=True, timeout=90):
    done = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=timeout)
    if check and done.returncode:
        raise RuntimeError(f"{args[:4]} failed: {done.stderr[-1200:]}")
    return done


def wait_sql(dsn, *, recovery=None, deadline=75):
    end = time.monotonic() + deadline
    last = None
    while time.monotonic() < end:
        try:
            with connect(dsn, connect_timeout=2) as db, db.cursor() as cursor:
                cursor.execute("SELECT pg_is_in_recovery()")
                observed = cursor.fetchone()[0]
                if recovery is None or observed == recovery:
                    return
        except (OperationalError, OSError) as exc:
            last = exc
        time.sleep(1)
    raise RuntimeError(f"PostgreSQL did not become ready (expect recovery={recovery}): {last}")


def drill():
    if os.environ.get("AGENTBRIDGE_DISPOSABLE_REPLICA_DRILL") != "1":
        raise RuntimeError("separately isolated disposable replica drill must be enabled")
    marker = uuid.uuid4().hex[:10]
    primary = "ab-ha-primary-" + marker
    standby = "ab-ha-standby-" + marker
    network = "ab-ha-network-" + marker
    volume = "ab-ha-replica-" + marker
    password = "disposable-replica-only-" + marker
    dsn = lambda port: (
        f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres")
    created = []
    try:
        run(["docker", "volume", "create", volume])
        created.append(("volume", volume))
        run(["docker", "network", "create", network])
        created.append(("network", network))
        run(["docker", "run", "-d", "--name", primary, "--network", network,
             "--network-alias", "ab-primary", "--publish", "127.0.0.1::5432",
             "-e", "POSTGRES_PASSWORD=" + password, "postgres:16",
             "postgres", "-c", "wal_level=replica",
             "-c", "max_wal_senders=10"])
        created.append(("container", primary))
        primary_port = int(run(["docker", "port", primary, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1])
        wait_sql(dsn(primary_port), recovery=False)
        # PGDATA of standby is a *separate* Docker-managed volume.
        # The postgres Docker entrypoint adds host auth; explicitly add a
        # replication-only scram rule if the image doesn't have one.
        run(["docker", "exec", primary, "bash", "-c",
             "echo 'host replication all 0.0.0.0/0 scram-sha-256' >> "
             "/var/lib/postgresql/data/pg_hba.conf"])
        with connect(dsn(primary_port), autocommit=True) as admin:
            admin.execute("SELECT pg_reload_conf()")
        run(["docker", "run", "--rm", "--network", network,
             "-v", f"{volume}:/var/lib/postgresql/data",
             "-e", "PGPASSWORD=" + password,
             "postgres:16", "bash", "-c",
             "pg_basebackup -h ab-primary -p 5432 -U postgres "
             "-D /var/lib/postgresql/data -X stream -R -c fast --no-password "
             "&& chown -R postgres:postgres /var/lib/postgresql/data"], timeout=120)
        run(["docker", "run", "-d", "--name", standby, "--network", network,
             "--publish", "127.0.0.1::5432",
             "-v", f"{volume}:/var/lib/postgresql/data",
             "-e", "POSTGRES_PASSWORD=" + password,
             "postgres:16", "postgres",
             "-c", "hot_standby=on"])
        created.append(("container", standby))
        standby_port = int(run(["docker", "port", standby, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1])
        wait_sql(dsn(standby_port), recovery=True)
        agent, operation = "ha-agent-" + marker, "ha-operation-" + marker
        store = PostgresStore(dsn(primary_port))
        try:
            ledger = OperationLedger(store)
            ledger.claim(agent, operation, "exact-action-fingerprint")
            assert ledger.get(agent, operation)["state"] == "unknown"
        finally:
            store.close()
        # Wait for physical replication of this *committed* write.
        deadline = time.monotonic() + 30
        replicated = False
        while time.monotonic() < deadline:
            with connect(dsn(standby_port), autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.agent_operations')")
                    if cur.fetchone()[0] is not None:
                        cur.execute(
                            "SELECT state FROM agent_operations WHERE agent_id=%s "
                            "AND operation_id=%s", (agent, operation))
                        row = cur.fetchone()
                        if row == ("unknown",):
                            replicated = True
                            break
            time.sleep(.5)
        assert replicated, "committed state was not replicated before fencing"
        # FENCE old primary, then promote standby, avoiding synthetic split brain.
        failover_started=time.monotonic()
        run(["docker", "stop", "--time", "4", primary], timeout=30)
        with connect(dsn(standby_port), autocommit=True) as conn:
            conn.execute("SELECT pg_promote(wait => true, wait_seconds => 30)")
        wait_sql(dsn(standby_port), recovery=False)
        failover_seconds=round(time.monotonic()-failover_started,3)
        if failover_seconds>60:
            raise AssertionError("disposable fencing and promotion RTO smoke threshold exceeded")
        recovered = PostgresStore(dsn(standby_port))
        try:
            ledger = OperationLedger(recovered)
            assert ledger.get(agent, operation)["state"] == "unknown"
            try:
                ledger.claim(agent, operation, "exact-action-fingerprint")
                raise AssertionError("promoted standby replayed claimed action")
            except OperationConflict:
                pass
        finally:
            recovered.close()
        return {
            "kind": "disposable-postgresql16-streaming-replica-promotion",
            "replication_confirmed_before_fence": replicated,
            "old_primary_fenced": True,
            "standby_promoted": True,
            "unknown_operation_preserved": True,
            "replay_denied": True,
            "measured_fence_to_promotion_seconds":failover_seconds,
            "disposable_smoke_max_seconds":60,
            "witnessed_operation_rpo_lost":0,
            "limitations": "No automatic HA, true network partition, witness fencing, RPO/RTO or managed provider",
        }
    finally:
        for kind, identifier in reversed(created):
            if kind == "container":
                run(["docker", "rm", "-f", identifier], check=False)
            elif kind == "network":
                run(["docker", "network", "rm", identifier], check=False)
            else:
                run(["docker", "volume", "rm", "-f", identifier], check=False)


if __name__ == "__main__":
    report = drill()
    path = os.environ.get("AGENTBRIDGE_REPLICA_DRILL_REPORT")
    if path:
        with open(path, "w", encoding="utf8") as out:
            json.dump(report, out, indent=2)
    print(json.dumps(report, indent=2))
