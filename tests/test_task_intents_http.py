"""Real signed HTTP intent acceptance/inspection remains queued and owner scoped."""

from dataclasses import asdict, replace

import httpx
import pytest

from src.api.tenant_control_plane import create_tenant_app
from src.governance.task_intents import IntentLimits
from src.governance.tenant_kernel import principal_owner
from src.protocols.task_lifecycle import TaskLifecycle
from src.serve.tenant_agent_client import TenantAgentClient
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_task_intents import authenticated, count, submission
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_http import operator, signed
from tests.test_tenant_kernel import human_grant
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


@pytest.fixture
def queued_http(queued_app, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    return create_tenant_app(queued_app[0])


@pytest.mark.asyncio
async def test_real_client_queues_and_inspects_without_execution(queued_app, queued_http, loopback_server, monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("intent HTTP routes cannot execute")

    monkeypatch.setattr("src.proxy.transport.invoke_target", prohibited)
    store = queued_app[0]._runtimes["alpha"].store
    budget = store.get_budget("worker")
    with loopback_server(lambda _: queued_http) as (url, _):
        async with TenantAgentClient(url, "alpha", queued_app[2]["alpha"], allow_loopback_http=True) as client:
            value = submission()
            result = await client.submit_task(
                value["src"], value["dst"], value["wire"], task_id=value["task_id"],
                context_id=value["context_id"], operation_id=value["operation_id"], target_id=value["target_id"],
            )
            assert result["phase"] == "queued" and result["execution_admitted"] is False
            assert result == await client.task_intent("native-task")
            assert (await client.task("native-task"))["source_protocol"] == "agentbridge"
            assert [item["state"] for item in await client.task_events("native-task")] == ["submitted"]
            with pytest.raises(httpx.HTTPStatusError) as denied:
                await client.operation(value["operation_id"])
            assert denied.value.response.status_code == 403
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(queued_app, "beta", data={"request_scope": "task.intent.read", "task_id": "native-task"})
            assert (await client.post("/v2/tasks/intents/read", content=raw, headers=headers)).status_code == 403
            assert (await client.post("/v2/tasks/execute", json={})).status_code == 404
    assert count(store, "agent_operations") == count(store, "operation_reservations") == 0
    assert store.get_budget("worker") == budget


@pytest.mark.asyncio
async def test_real_network_exact_body_strict_scope_and_duplicate_submission(queued_app, queued_http, loopback_server):
    with loopback_server(lambda _: queued_http) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(queued_app, data=submission())
            assert (await client.post("/v2/tasks/submit", content=raw + b" ", headers=headers)).status_code == 403
            accepted = await client.post("/v2/tasks/submit", content=raw, headers=headers)
            assert accepted.status_code == 202, accepted.text
            original = accepted.json()
            for change in ({}, {"context_id": "changed"}, {"task_id": "new-task"}):
                payload, proof = signed(queued_app, data=submission(**change))
                assert (await client.post("/v2/tasks/submit", content=payload, headers=proof)).status_code == 409
            for change in ({"owner_id": "untrusted"}, {"cost": 0}, {"principal": {}}, {"target": {}},
                           {"request_scope": "task.read"}, {"target_id": None}):
                payload, proof = signed(queued_app, data=submission(**change))
                assert (await client.post("/v2/tasks/submit", content=payload, headers=proof)).status_code == 400
            duplicate, proof = signed(queued_app, raw=raw[:-1] + b',"task_id":"changed"}')
            assert (await client.post("/v2/tasks/submit", content=duplicate, headers=proof)).status_code == 400
            payload, proof = signed(queued_app, data={"request_scope": "task.read", "task_id": "native-task"})
            assert (await client.post("/v2/tasks/intents/read", content=payload, headers=proof)).status_code == 400
            payload, proof = signed(queued_app, data={"request_scope": "task.intent.read", "task_id": "native-task"})
            assert (await client.post("/v2/tasks/intents/read", content=payload, headers=proof)).json() == original
    assert count(queued_app[0]._runtimes["alpha"].store, "task_lifecycle_events") == 1


@pytest.mark.asyncio
async def test_real_network_owner_grant_and_revocation_are_rechecked(queued_app, queued_http, loopback_server):
    grant = human_grant(queued_app)
    with loopback_server(lambda _: queued_http) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(queued_app, data=submission(), delegation=grant)
            accepted = await client.post("/v2/tasks/submit", content=raw, headers=headers)
            assert accepted.status_code == 202
            read = {"request_scope": "task.intent.read", "task_id": "native-task"}
            for delegation in (None, human_grant(queued_app, "other-human")):
                raw, headers = signed(queued_app, data=read, delegation=delegation)
                assert (await client.post("/v2/tasks/intents/read", content=raw, headers=headers)).status_code == 403
            replacement = human_grant(queued_app)
            raw, headers = signed(queued_app, data=read, delegation=replacement)
            assert (await client.post("/v2/tasks/intents/read", content=raw, headers=headers)).status_code == 200
            queued_app[4].revoke_delegation(queued_app[5], "alpha", replacement)
            raw, headers = signed(queued_app, data=read, delegation=replacement)
            assert (await client.post("/v2/tasks/intents/read", content=raw, headers=headers)).status_code == 403
    assert count(queued_app[0]._runtimes["alpha"].store, "task_intents_v1") == 1


@pytest.mark.asyncio
async def test_operator_capacity_is_persisted_tenant_scoped_and_admin_only(queued_app, queued_http):
    limits = asdict(replace(IntentLimits(), max_intents=1))
    directory, owner = queued_app[4:]
    directory.enroll_member(owner, "alpha", ISSUER, "viewer", role="tenant_viewer")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=queued_http), base_url="http://local") as client:
        for subject in ("viewer", "human"):
            assert (await client.put("/v2/operator/task-intent-capacity", json=limits,
                                    headers=operator(queued_app, subject=subject))).status_code == 403
        assert (await client.put("/v2/operator/task-intent-capacity", json=limits,
                                headers=operator(queued_app))).status_code == 200
        read = await client.get("/v2/operator/task-intent-capacity", headers=operator(queued_app))
        assert read.json()["max_intents"] == 1
        beta = await client.get("/v2/operator/task-intent-capacity", headers=operator(queued_app, "beta"))
        assert beta.json()["max_intents"] == 1024
        raw, headers = signed(queued_app, data=submission())
        assert (await client.post("/v2/tasks/submit", content=raw, headers=headers)).status_code == 202
        raw, headers = signed(queued_app, data=submission(task_id="second", operation_id="second-operation-12345"))
        assert (await client.post("/v2/tasks/submit", content=raw, headers=headers)).status_code == 429
    assert queued_app[0]._runtimes["alpha"].task_intents.capacity()["used_intents"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("saturation", ["owner", "history", "event"])
async def test_submit_lifecycle_saturation_is_429_with_free_intent_capacity(
    queued_app, queued_http, loopback_server, saturation
):
    runtime = queued_app[0]._runtimes["alpha"]
    session, _, _ = authenticated(queued_app)
    if saturation == "owner":
        runtime.tasks.max_active = 1
    if saturation == "history":
        runtime.tasks.set_history_capacity(1)
    if saturation in ("owner", "history"):
        runtime.tasks.create(principal_owner(session.principal), TaskLifecycle("held-task", "held-context", "a2a"))
    else:
        runtime.tasks.set_event_capacity(4096)
    capacity = runtime.task_intents.capacity()
    assert capacity["used_intents"] == 0 and capacity["max_intents"] > 0
    audit = runtime.store.load_audit_head()
    before = {table: count(runtime.store, table) for table in (
        "task_intents_v1", "task_lifecycle_snapshots", "task_lifecycle_events", "agent_operations"
    )}
    with loopback_server(lambda _: queued_http) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(queued_app, data=submission())
            response = await client.post("/v2/tasks/submit", content=raw, headers=headers)
    assert {table: count(runtime.store, table) for table in before} == before
    assert runtime.store.load_audit_head() == audit
    assert response.status_code == 429, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("source,wire", [
    ("openai", {"function": [1]}),
    ("acp", {"agent_name": "read", "input": [{"parts": [None]}]}),
])
async def test_malformed_nested_action_is_400_without_acceptance(
    queued_app, queued_http, loopback_server, source, wire
):
    runtime = queued_app[0]._runtimes["alpha"]
    audit = runtime.store.load_audit_head()
    budget = runtime.store.get_budget("worker")
    with loopback_server(lambda _: queued_http) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(queued_app, data=submission(src=source, wire=wire))
            response = await client.post("/v2/tasks/submit", content=raw, headers=headers)
    for table in ("task_intents_v1", "task_lifecycle_snapshots", "task_lifecycle_events", "agent_operations"):
        assert count(runtime.store, table) == 0
    assert runtime.store.load_audit_head() == audit
    assert runtime.store.get_budget("worker") == budget
    assert response.status_code == 400, response.text
