"""Shared SQL stream admission, stale allocation fencing and actual tenant SSE."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import httpx
import pytest

from src.api.tenant_control_plane import create_tenant_app
from src.governance.authority import AuthorityDenied, AuthorityDirectory
from src.governance.durable_stream_leases import DurableStreamLeases, FleetStreamLimits, StreamCapacity, StreamLease
from src.governance.identity import AgentIdentity
from src.governance.tenant_kernel import principal_owner
from src.protocols.task_lifecycle import TaskLifecycle, TaskState
from src.serve.a2a_status import StreamLimits, _Streams
from src.serve.tenant_task_stream import TenantTaskStream, acquire_stream_lease
from tests.test_authority import ISSUER, agent_request
from tests.test_authority import authority as authority
from tests.test_delegation_resource_isolation import scoped_history as scoped_history
from tests.test_tenant_http import signed
from tests.test_tenant_kernel import signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def coordinator(app, **limits):
    return DurableStreamLeases(app[4], limits=FleetStreamLimits(**limits))


def test_two_authority_replicas_share_global_capacity_and_recheck_after_race(tenant_app):
    # Separate stores/connections and separate principal seals, same authority data.
    first = coordinator(tenant_app, max_streams=1)
    directory = tenant_app[4]
    store = directory.store
    from src.governance.store import PostgresStore, SqliteStore
    if isinstance(store, SqliteStore):
        other_store = SqliteStore(store._db.execute("PRAGMA database_list").fetchone()["file"])
    else:
        from psycopg.conninfo import make_conninfo
        other_store = PostgresStore(make_conninfo(store._db.info.dsn, password=store._db.info.password))
    other = AuthorityDirectory(other_store, verifiers=directory.verifiers)
    second = DurableStreamLeases(other, limits=first.limits)
    a = signed_session(tenant_app)[0].principal
    # Obtain a real principal from the second directory rather than copying its seal.
    raw, headers = signed(tenant_app, "beta", data={"request_scope":"task.stream","task_id":"task"})
    b = other.authenticate_agent("beta", "worker", headers["x-nonce"], raw, headers["x-signature"])

    def acquire(pair):
        service, principal = pair
        try:
            return service.acquire(principal)
        except StreamCapacity:
            return None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(acquire, ((first, a), (second, b))))
        assert sum(lease is not None for lease in result) == 1
        assert first.usage()["active_stream_allocations"] == second.usage()["active_stream_allocations"] == 1
        for service, lease in zip((first, second), result):
            if lease is not None:
                service.release(lease)
        assert first.usage()["active_stream_allocations"] == 0
    finally:
        other_store.close()


def test_per_tenant_per_owner_scope_and_revocation(tenant_app):
    service = coordinator(tenant_app, max_streams=4, max_per_tenant=1, max_per_owner=1)
    a, b = (signed_session(tenant_app, t)[0].principal for t in ("alpha", "beta"))
    lease = service.acquire(a)
    with pytest.raises(StreamCapacity):
        service.acquire(a)
    beta = service.acquire(b)
    with pytest.raises(AuthorityDenied):
        service.renew(b, lease)
    tenant_app[4].revoke_agent(tenant_app[5], "alpha", "worker")
    with pytest.raises(AuthorityDenied):
        service.renew(a, lease)
    service.release(lease)
    service.release(lease)
    service.renew(b, beta)
    assert service.usage()["active_stream_allocations"] == 1


def test_expired_or_released_allocation_cannot_resurrect_after_new_admission(tenant_app):
    service = coordinator(tenant_app, max_streams=1, lease_seconds=.05, max_seconds=.2)
    principal = signed_session(tenant_app)[0].principal
    old = service.acquire(principal)
    time.sleep(.08)
    current = service.acquire(principal)
    with pytest.raises(StreamCapacity, match="expired or released"):
        service.renew(principal, old)
    service.release(old)
    service.renew(principal, current)
    assert service.usage()["active_stream_allocations"] == 1
    service.release(current)
    with pytest.raises(StreamCapacity):
        service.renew(principal, current)


def test_renewal_never_extends_absolute_lifetime(tenant_app):
    service = coordinator(tenant_app, lease_seconds=1, max_seconds=2)
    principal = signed_session(tenant_app)[0].principal
    lease = service.acquire(principal)
    with service._atomic() as cur:
        original = service._execute(cur, "SELECT deadline FROM stream_leases_v1 WHERE identity=?", (lease.identity,)).fetchone()["deadline"]
    for _ in range(3):
        service.renew(principal, lease)
    with service._atomic() as cur:
        row = service._execute(cur, "SELECT deadline,expires FROM stream_leases_v1 WHERE identity=?", (lease.identity,)).fetchone()
        assert row["deadline"] == original and row["expires"] <= original
        # Move only the absolute deadline behind database time while renewal
        # expiry remains in the future, isolating the hard-lifetime condition.
        now = service._now(cur)
        service._execute(cur, "UPDATE stream_leases_v1 SET deadline=?,expires=? WHERE identity=?", (now-1, now+10, lease.identity))
    with pytest.raises(StreamCapacity):
        service.renew(principal, lease)


@pytest.mark.parametrize("damage", ["missing-row", "bad-version", "partial"])
def test_policy_corruption_or_replica_configuration_drift_fails_closed(tenant_app, damage):
    service = coordinator(tenant_app)
    with pytest.raises(StreamCapacity, match="policy"):
        coordinator(tenant_app, max_streams=1)
    db = service.store._db
    if damage == "missing-row":
        db.execute("DELETE FROM stream_lease_policy_v1")
    elif damage == "bad-version":
        db.execute("UPDATE stream_lease_policy_v1 SET version=99")
    else:
        db.execute("DROP TABLE stream_leases_v1")
    with pytest.raises(StreamCapacity):
        coordinator(tenant_app)


def test_failed_renewal_on_database_error_does_not_fall_back(tenant_app, monkeypatch):
    service = coordinator(tenant_app)
    principal = signed_session(tenant_app)[0].principal
    lease = service.acquire(principal)
    monkeypatch.setattr(service, "_now", lambda _: (_ for _ in ()).throw(RuntimeError("database unavailable")))
    with pytest.raises(RuntimeError, match="database unavailable"):
        service.renew(principal, lease)


def seed_task(app, tenant="alpha", state=TaskState.SUBMITTED):
    session = signed_session(app, tenant)[0]
    tasks = app[0]._runtimes[tenant].tasks
    tasks.create(principal_owner(session.principal), TaskLifecycle("task", "context", "a2a"))
    if state != TaskState.SUBMITTED:
        tasks.transition(principal_owner(session.principal), "task", TaskState.WORKING, expected_sequence=0)
        tasks.transition(principal_owner(session.principal), "task", state, expected_sequence=1)
    return session


def application(app, monkeypatch, *, local_limits=None, **fleet):
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    return create_tenant_app(app[0], stream_limits=local_limits or StreamLimits(poll_seconds=.01, heartbeat_seconds=.02, max_seconds=1),
                             fleet_stream_limits=FleetStreamLimits(**{"lease_seconds":.2,"max_seconds":1,**fleet}))


async def first_event(lines):
    async for line in lines:
        if line.startswith("data: "):
            return json.loads(line[6:])
    pytest.fail("stream closed without status")


@pytest.mark.asyncio
async def test_actual_network_stream_replay_cross_tenant_and_disconnect_cleanup(tenant_app, monkeypatch, loopback_server):
    seed_task(tenant_app, state=TaskState.COMPLETED)
    app = application(tenant_app, monkeypatch)
    with loopback_server(lambda _: app) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task","after_sequence":1})
            response = await client.post("/v2/tasks/stream", content=raw, headers=headers)
            assert response.status_code == 200
            data = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert [row["sequence"] for row in data] == [2] and data[0]["state"] == "completed"
            raw, headers = signed(tenant_app, "beta", data={"request_scope":"task.stream","task_id":"task"})
            assert (await client.post("/v2/tasks/stream", content=raw, headers=headers)).status_code == 403
            raw, headers = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task","after_sequence":99})
            assert (await client.post("/v2/tasks/stream", content=raw, headers=headers)).status_code == 400
    assert app.state.status_streams.total == 0
    assert app.state.stream_leases.usage()["active_stream_allocations"] == 0


@pytest.mark.asyncio
async def test_two_http_apps_share_cap_and_revocation_closes_current_stream(tenant_app, monkeypatch, loopback_server):
    seed_task(tenant_app)
    first = application(tenant_app, monkeypatch, max_streams=1)
    second = application(tenant_app, monkeypatch, max_streams=1)
    with loopback_server(lambda _: first) as (url_a, _), loopback_server(lambda _: second) as (url_b, _):
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            raw, headers = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task"})
            async with client.stream("POST", url_a+"/v2/tasks/stream", content=raw, headers=headers) as response:
                assert response.status_code == 200
                lines = response.aiter_lines()
                assert (await first_event(lines))["state"] == "submitted"
                raw2, headers2 = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task"})
                assert (await client.post(url_b+"/v2/tasks/stream", content=raw2, headers=headers2)).status_code == 429
                tenant_app[4].revoke_agent(tenant_app[5], "alpha", "worker")
                # The response terminates without publishing later task state.
                remaining = [line async for line in lines]
                assert not any(line.startswith("data: ") for line in remaining)
            deadline = time.monotonic()+2
            while first.state.stream_leases.usage()["active_stream_allocations"]:
                assert time.monotonic() < deadline
                await asyncio.sleep(.01)
    assert first.state.status_streams.total == 0


@pytest.mark.parametrize("field,value", [("max_streams",True),("max_streams",0),("max_per_owner",10001),("lease_seconds",float("nan")),("lease_seconds",31),("max_seconds",False)])
def test_invalid_fleet_limits(field, value):
    with pytest.raises(ValueError):
        FleetStreamLimits(**{field:value})


def other_machine(app, tenant="alpha"):
    identity = AgentIdentity.generate("other-worker")
    app[1][tenant].enroll_agent(identity.agent_id, identity.public_key_hex, capabilities=("read",), targets=("ledger",))
    return agent_request(app[4], tenant=tenant, identity=identity)


def test_tenant_cap_aggregates_distinct_owners_without_consuming_another_tenant(tenant_app):
    service = coordinator(tenant_app, max_streams=4, max_per_tenant=1, max_per_owner=4)
    first = signed_session(tenant_app)[0].principal
    second = other_machine(tenant_app)
    assert service._scope(first) != service._scope(second)
    service.acquire(first)
    with pytest.raises(StreamCapacity):
        service.acquire(second)
    service.acquire(signed_session(tenant_app, "beta")[0].principal)
    assert service.usage()["active_stream_allocations"] == 2


def test_human_cap_survives_replacement_grants_and_different_delegated_agents(tenant_app):
    service = coordinator(tenant_app, max_streams=4, max_per_tenant=4, max_per_owner=1)
    directory = tenant_app[4]
    human = directory.authenticate_operator(ISSUER, tenant_app[3]("human", tenant="alpha"), tenant_id="alpha")

    def grant(agent):
        return directory.grant_delegation(tenant_app[1]["alpha"].principal, human, agent,
                                          capabilities=("read",), targets=("ledger",), expires_at=time.time()+60)

    first_grant, replacement = grant("worker"), grant("worker")
    first = signed_session(tenant_app, delegation=first_grant)[0].principal
    renewed = signed_session(tenant_app, delegation=replacement)[0].principal
    identity = AgentIdentity.generate("other-worker")
    tenant_app[1]["alpha"].enroll_agent(identity.agent_id, identity.public_key_hex, capabilities=("read",), targets=("ledger",))
    different_agent = agent_request(directory, identity=identity, delegation=grant(identity.agent_id))
    service.acquire(first)
    assert first.delegation_id != renewed.delegation_id
    assert service._scope(first) == service._scope(renewed) != service._scope(different_agent)
    for principal in (renewed, different_agent):
        with pytest.raises(StreamCapacity):
            service.acquire(principal)
    # The agent's own machine scope is a separate owner from its human delegate.
    service.acquire(signed_session(tenant_app)[0].principal)
    assert service.usage()["active_stream_allocations"] == 2


@pytest.mark.parametrize("damage", ["missing-row", "bad-version", "changed-policy"])
def test_running_replica_rechecks_coordination_policy_on_every_operation(tenant_app, damage):
    service = coordinator(tenant_app)
    principal = signed_session(tenant_app)[0].principal
    lease = service.acquire(principal)
    if damage == "missing-row":
        service.store._db.execute("DELETE FROM stream_lease_policy_v1")
    elif damage == "bad-version":
        service.store._db.execute("UPDATE stream_lease_policy_v1 SET version=2")
    else:
        service.store._db.execute("UPDATE stream_lease_policy_v1 SET policy='{}'")
    for operation in (lambda: service.acquire(principal), lambda: service.renew(principal, lease), service.usage):
        with pytest.raises(StreamCapacity, match="policy"):
            operation()
    service.release(lease)


@pytest.mark.parametrize("table", ["stream_lease_policy_v1", "stream_leases_v1"])
def test_coordination_views_are_not_silently_accepted_as_tables(tenant_app, table):
    service = coordinator(tenant_app)
    service.store._db.execute("DROP TABLE " + table)
    service.store._db.execute("CREATE VIEW " + table + " AS SELECT 1 AS placeholder")
    with pytest.raises(StreamCapacity, match="ordinary stream lease tables"):
        coordinator(tenant_app)


@pytest.mark.asyncio
async def test_cancelled_admission_releases_late_database_result(tenant_app, monkeypatch):
    service = coordinator(tenant_app, max_streams=1)
    principal = signed_session(tenant_app)[0].principal
    local = _Streams(StreamLimits(max_streams=1))
    entered, resume, cleaned = threading.Event(), threading.Event(), threading.Event()
    acquire, release = service.acquire, service.release

    def blocked_acquire(value):
        entered.set()
        assert resume.wait(3)
        return acquire(value)

    def tracked_release(lease):
        release(lease)
        cleaned.set()

    monkeypatch.setattr(service, "acquire", blocked_acquire)
    monkeypatch.setattr(service, "release", tracked_release)
    pending = asyncio.create_task(acquire_stream_lease(service, principal, local.acquire("owner")))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 1)
        assert local.total == 0
    finally:
        resume.set()
    assert await asyncio.to_thread(cleaned.wait, 3)
    assert service.usage()["active_stream_allocations"] == 0
    # The single fleet slot is immediately reusable, without waiting for TTL.
    service.release(acquire(principal))


class ConnectedRequest:
    async def is_disconnected(self):
        return False


def response_for(app, service, *, state=TaskState.COMPLETED, after_sequence=-1):
    session = seed_task(app, state=state)
    local = _Streams(StreamLimits())
    release = local.acquire("owner")
    response = TenantTaskStream(ConnectedRequest(), session, "task", after_sequence=after_sequence,
                                coordinator=service, lease=service.acquire(session.principal),
                                limits=StreamLimits(max_seconds=2, poll_seconds=.01), release_local=release)
    return response, local


async def unused_receive():
    pytest.fail("ASGI 2.4 response must not poll receive in this harness")


@pytest.mark.asyncio
async def test_authority_failure_before_response_headers_releases_both_slots(tenant_app):
    service = coordinator(tenant_app, lease_seconds=1, max_seconds=2)
    response, local = response_for(tenant_app, service)
    tenant_app[4].revoke_agent(tenant_app[5], "alpha", "worker")
    messages = []

    async def send(message):
        messages.append(message)

    with pytest.raises(AuthorityDenied):
        await response({"type":"http","asgi":{"spec_version":"2.4"}}, unused_receive, send)
    assert messages == []  # No body-before-start, including an empty body.
    assert local.total == service.usage()["active_stream_allocations"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fence", ["revocation", "expiry"])
async def test_each_buffered_chunk_rechecks_authority_and_allocation(tenant_app, fence):
    service = coordinator(tenant_app, lease_seconds=1, max_seconds=2)
    response, local = response_for(tenant_app, service)
    sequences = []

    async def send(message):
        body = message.get("body", b"").decode()
        if "data: " not in body:
            return
        sequences.append(json.loads(body.split("data: ", 1)[1])["sequence"])
        if len(sequences) == 1:
            if fence == "revocation":
                tenant_app[4].revoke_agent(tenant_app[5], "alpha", "worker")
            else:
                with service._atomic() as cur:
                    service._execute(cur, "UPDATE stream_leases_v1 SET expires=?", (service._now(cur)-1,))

    await response({"type":"http","asgi":{"spec_version":"2.4"}}, unused_receive, send)
    assert sequences == [0]  # WORKING/COMPLETED were fetched in the same page.
    assert local.total == service.usage()["active_stream_allocations"] == 0


@pytest.mark.asyncio
async def test_stalled_asgi_body_send_times_out_and_releases_capacity(tenant_app):
    service = coordinator(tenant_app, lease_seconds=.4, max_seconds=2)
    response, local = response_for(tenant_app, service)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def send(message):
        if message.get("body"):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    await asyncio.wait_for(response({"type":"http","asgi":{"spec_version":"2.4"}}, unused_receive, send), 2)
    assert started.is_set() and cancelled.is_set()
    assert local.total == service.usage()["active_stream_allocations"] == 0


@pytest.mark.asyncio
async def test_quiet_stream_renews_across_multiple_leases_and_client_disconnect_releases(tenant_app, monkeypatch, loopback_server):
    seed_task(tenant_app)
    local = StreamLimits(poll_seconds=.01, heartbeat_seconds=.03, max_seconds=2)
    first = application(tenant_app, monkeypatch, local_limits=local, max_streams=1, max_seconds=2)
    second = application(tenant_app, monkeypatch, local_limits=local, max_streams=1, max_seconds=2)
    with loopback_server(lambda _: first) as (url_a, _), loopback_server(lambda _: second) as (url_b, _):
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            raw, headers = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task"})
            async with client.stream("POST", url_a+"/v2/tasks/stream", content=raw, headers=headers) as response:
                assert response.status_code == 200
                lines = response.aiter_lines()
                assert (await first_event(lines))["sequence"] == 0
                started, heartbeats = time.monotonic(), 0
                async for line in lines:
                    heartbeats += line == ": keep-alive"
                    if time.monotonic()-started >= .5:
                        break
                assert heartbeats >= 2
                assert first.state.stream_leases.usage()["active_stream_allocations"] == 1
                raw2, headers2 = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task"})
                assert (await client.post(url_b+"/v2/tasks/stream", content=raw2, headers=headers2)).status_code == 429
            deadline = time.monotonic()+2
            while first.state.stream_leases.usage()["active_stream_allocations"] or first.state.status_streams.total:
                assert time.monotonic() < deadline
                await asyncio.sleep(.01)
    assert second.state.status_streams.total == 0


def test_actual_worker_death_recovers_only_after_lease_expiry_and_fences_old_worker(tenant_app):
    from src.governance.store import SqliteStore
    service = coordinator(tenant_app, max_streams=1, lease_seconds=.5, max_seconds=2)
    store = service.store
    if isinstance(store, SqliteStore):
        config = {"backend":"sqlite", "path":store._db.execute("PRAGMA database_list").fetchone()["file"]}
    else:
        from psycopg.conninfo import make_conninfo
        config = {"backend":"postgres", "dsn":make_conninfo(store._db.info.dsn, password=store._db.info.password)}
    raw, headers = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task"})
    config.update(body=raw.decode(), headers=headers, limits=asdict(service.limits),
                  verifiers={issuer:asdict(verifier.config) for issuer,verifier in tenant_app[4].verifiers.items()})
    script = """
import json,os
from dataclasses import asdict
from src.governance.authority import AuthorityDirectory
from src.governance.durable_stream_leases import DurableStreamLeases,FleetStreamLimits
from src.governance.store import SqliteStore,PostgresStore
from src.api.auth_oidc import OidcConfig,OidcVerifier
c=json.loads(os.environ['AGENTBRIDGE_STREAM_CRASH'])
s=SqliteStore(c['path']) if c['backend']=='sqlite' else PostgresStore(c['dsn'])
d=AuthorityDirectory(s,verifiers={issuer:OidcVerifier(OidcConfig(**config)) for issuer,config in c['verifiers'].items()}); h=c['headers']
p=d.authenticate_agent('alpha','worker',h['x-nonce'],c['body'].encode(),h['x-signature'])
lease=DurableStreamLeases(d,limits=FleetStreamLimits(**c['limits'])).acquire(p)
print(json.dumps(asdict(lease)),flush=True)
os._exit(73)
"""
    result = subprocess.run([sys.executable,"-c",script], env={**os.environ,"AGENTBRIDGE_STREAM_CRASH":json.dumps(config)},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 73, result.stderr
    old = StreamLease(**json.loads(result.stdout))
    principal = signed_session(tenant_app)[0].principal
    assert service.usage()["active_stream_allocations"] == 1
    with pytest.raises(StreamCapacity):
        service.acquire(principal)
    time.sleep(.65)
    current = service.acquire(principal)
    with pytest.raises(StreamCapacity):
        service.renew(principal, old)
    service.release(old)
    service.renew(principal, current)
    assert service.usage()["active_stream_allocations"] == 1
    service.release(current)


@pytest.mark.asyncio
async def test_signed_task_and_cursor_exact_scope_replay_does_not_execute(scoped_history, monkeypatch):
    app, grant, original, *_ = scoped_history
    tasks = app[0]._runtimes["alpha"].tasks
    owner = principal_owner(original.principal)
    tasks.create(owner, TaskLifecycle("delegated-task", "private-context", "a2a"))
    tasks.transition(owner, "delegated-task", TaskState.WORKING, expected_sequence=0)
    tasks.transition(owner, "delegated-task", TaskState.COMPLETED, expected_sequence=1)
    http_app = application(app, monkeypatch)
    before = app[0]._runtimes["alpha"].store.get_budget("worker")
    data = {"request_scope":"task.stream","task_id":"delegated-task","after_sequence":1}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app), base_url="http://local") as client:
        for delegation in (None, grant(capabilities=("read",)), grant(targets=("ledger",))):
            raw, headers = signed(app, data=data, delegation=delegation)
            assert (await client.post("/v2/tasks/stream", content=raw, headers=headers)).status_code == 403
        raw, headers = signed(app, data=data, delegation=grant())
        altered = json.dumps({**data,"after_sequence":-1}).encode()
        assert (await client.post("/v2/tasks/stream", content=altered, headers=headers)).status_code == 403
        raw, headers = signed(app, data=data, delegation=grant())
        altered = json.dumps({**data,"task_id":"other-task"}).encode()
        assert (await client.post("/v2/tasks/stream", content=altered, headers=headers)).status_code == 403
        raw, headers = signed(app, data=data, delegation=grant())
        result = await client.post("/v2/tasks/stream?after_sequence=-1", content=raw, headers={**headers,"last-event-id":"0"})
        assert result.status_code == 200
        rows = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
        assert [(row["task_id"],row["sequence"],row["state"]) for row in rows] == [("delegated-task",2,"completed")]
    after = app[0]._runtimes["alpha"].store.get_budget("worker")
    assert before == after
    assert app[0]._runtimes["alpha"].operations.get("worker", "delegated-task") is None
    assert http_app.state.status_streams.total == http_app.state.stream_leases.usage()["active_stream_allocations"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", [True, -2, 2**63, 1.0])
async def test_invalid_signed_cursor_does_not_allocate(tenant_app, monkeypatch, cursor):
    seed_task(tenant_app)
    app = application(tenant_app, monkeypatch)
    raw, headers = signed(tenant_app, data={"request_scope":"task.stream","task_id":"task","after_sequence":cursor})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        assert (await client.post("/v2/tasks/stream", content=raw, headers=headers)).status_code == 400
    assert app.state.status_streams.total == app.state.stream_leases.usage()["active_stream_allocations"] == 0


@pytest.mark.parametrize("limits", [False, 0, {}])
def test_falsy_unvalidated_operator_limits_are_rejected(tenant_app, monkeypatch, limits):
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    with pytest.raises(ValueError, match="validated fleet"):
        DurableStreamLeases(tenant_app[4], limits=limits)
    with pytest.raises(ValueError, match="validated local"):
        create_tenant_app(tenant_app[0], stream_limits=limits)
    with pytest.raises(ValueError, match="validated fleet"):
        create_tenant_app(tenant_app[0], fleet_stream_limits=limits)



@pytest.mark.asyncio
@pytest.mark.parametrize("state", [TaskState.COMPLETED, TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED])
async def test_consumed_final_or_waiting_cursor_closes_without_heartbeats(tenant_app, state):
    service = coordinator(tenant_app, lease_seconds=1, max_seconds=2)
    response, local = response_for(tenant_app, service, state=state, after_sequence=2)
    messages = []

    async def send(message):
        if message["type"] == "http.response.body":
            assert messages and messages[0]["type"] == "http.response.start"
        messages.append(message)

    await response({"type":"http","asgi":{"spec_version":"2.4"}}, unused_receive, send)
    assert [message["type"] for message in messages] == ["http.response.start", "http.response.body"]
    assert messages[-1]["body"] == b"" and messages[-1]["more_body"] is False
    assert local.total == service.usage()["active_stream_allocations"] == 0


@pytest.mark.asyncio
async def test_state_change_after_empty_page_still_replays_final_event(tenant_app, monkeypatch):
    service = coordinator(tenant_app, lease_seconds=1, max_seconds=2)
    response, local = response_for(tenant_app, service, after_sequence=0)
    tasks = tenant_app[0]._runtimes["alpha"].tasks
    original = tasks.events
    reads = 0

    def events(*args, **kwargs):
        nonlocal reads
        reads += 1
        return [] if reads == 1 else original(*args, **kwargs)

    monkeypatch.setattr(tasks, "events", events)
    sequences = []

    async def send(message):
        body = message.get("body", b"").decode()
        if "data: " in body:
            sequences.append(json.loads(body.split("data: ", 1)[1])["sequence"])

    await response({"type":"http","asgi":{"spec_version":"2.4"}}, unused_receive, send)
    assert sequences == [1, 2]
    assert reads == 2
    assert local.total == service.usage()["active_stream_allocations"] == 0


@pytest.mark.asyncio
async def test_initial_response_denial_maps_to_http403_and_releases_allocations(tenant_app, monkeypatch, loopback_server):
    seed_task(tenant_app, state=TaskState.COMPLETED)
    app = application(tenant_app, monkeypatch)
    service = app.state.stream_leases
    original = service.renew

    def deny_before_headers(principal, lease):
        tenant_app[4].revoke_agent(tenant_app[5], "alpha", "worker")
        return original(principal, lease)

    monkeypatch.setattr(service, "renew", deny_before_headers)
    with loopback_server(lambda _: app) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(tenant_app, data={"request_scope":"task.stream", "task_id":"task"})
            response = await client.post("/v2/tasks/stream", content=raw, headers=headers)
            assert response.status_code == 403
            assert response.json() == {"detail":"resource or authority unavailable"}
    assert app.state.status_streams.total == service.usage()["active_stream_allocations"] == 0
