"""Real HTTP sockets, official SDK streaming, ownership and durable replay."""
import asyncio
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

pytest.importorskip("a2a")
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    Message,
    MessageSendParams,
    Part,
    Role,
    SendMessageRequest,
    TaskIdParams,
    TaskResubscriptionRequest,
    TextPart,
)

from src.api.auth_oidc import OidcConfig, OidcError, OidcVerifier
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import TaskLifecycle, TaskState
from src.serve.a2a_status import StreamLimits, create_a2a_status_app


@pytest.fixture
def state(network_sql_stores):
    key = generate_private_key(public_exponent=65537, key_size=2048)
    verifier = OidcVerifier(OidcConfig(issuer="https://issuer.example", audience="status",
        public_key_pem=key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()))
    store = network_sql_stores()
    tasks = DurableTaskLifecycle(store)
    tasks.create("alice", TaskLifecycle("task", "context", "a2a"))

    def headers(subject="alice", expired=False):
        token = jwt.encode({"iss": "https://issuer.example", "aud": "status", "sub": subject,
                            "exp": time.time() + (-10 if expired else 120)}, key, algorithm="RS256")
        return {"Authorization": "Bearer " + token, "Accept": "text/event-stream"}

    def factory(url, **kwargs):
        return create_a2a_status_app(tasks, verifier, public_url=url, allow_loopback_http=True,
                                    limits=kwargs.pop("limits", StreamLimits(max_seconds=2, page_size=1, poll_seconds=.01)), **kwargs)

    yield tasks, verifier, headers, factory, network_sql_stores
    store.close()


def rpc(method="tasks/get", task_id="task", **fields):
    return {"jsonrpc": "2.0", "id": "request", "method": method, "params": {"id": task_id}, **fields}


async def first_event(response, iterator=None):
    cursor = None
    async for line in (iterator if iterator is not None else response.aiter_lines()):
        if line.startswith("id: "):
            cursor = line[4:]
        elif line.startswith("data: "):
            return cursor, json.loads(line[6:])
    raise AssertionError("stream ended without an event")


async def released(app):
    deadline = time.monotonic() + 3
    while app.state.status_streams.total:
        assert time.monotonic() < deadline, "stream capacity leaked after disconnect"
        await asyncio.sleep(.02)


@pytest.mark.asyncio
async def test_official_sdk_consumes_ordered_task_and_terminal_status(state, loopback_server):
    tasks, _, headers, factory, _ = state
    tasks.transition("alice", "task", TaskState.WORKING, expected_sequence=0)
    tasks.transition("alice", "task", TaskState.COMPLETED, expected_sequence=1)
    with loopback_server(factory) as (url, app):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            card = await A2ACardResolver(http, url).get_agent_card()
            assert card.protocol_version == "0.3.0" and card.capabilities.streaming
            client = A2AClient(http, agent_card=card)
            request = TaskResubscriptionRequest(id="subscribe", params=TaskIdParams(id="task"))
            results = [item.model_dump(mode="json")["result"] async for item in client.resubscribe(request)]
            assert [item["metadata"]["agentbridge_sequence"] for item in results] == [0, 1, 2]
            assert [item["kind"] for item in results] == ["task", "status-update", "status-update"]
            assert results[-1]["final"] and results[-1]["status"]["state"] == "completed"
            message = Message(message_id="query", role=Role.user, task_id="task",
                              parts=[Part(root=TextPart(text="status"))])
            reply = await client.send_message(SendMessageRequest(id="query", params=MessageSendParams(message=message)))
            assert reply.model_dump(mode="json")["result"]["status"]["state"] == "completed"
        await released(app)


@pytest.mark.asyncio
async def test_disconnect_restart_and_cursor_replay_without_task_execution(state, loopback_server):
    tasks, verifier, headers, factory, path = state
    with loopback_server(factory) as (url, app):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            async with http.stream("POST", url + "/a2a", json=rpc("tasks/resubscribe")) as response:
                cursor, event = await first_event(response)
                assert event["result"]["metadata"]["agentbridge_sequence"] == 0
        await released(app)
    tasks.transition("alice", "task", TaskState.WORKING, expected_sequence=0)
    tasks.transition("alice", "task", TaskState.COMPLETED, expected_sequence=1)
    reopened = path()
    recovered = DurableTaskLifecycle(reopened)
    try:
        with loopback_server(lambda url: create_a2a_status_app(recovered, verifier, public_url=url,
                    allow_loopback_http=True, limits=StreamLimits(max_seconds=2, page_size=1, poll_seconds=.01))) as (url, app):
            async with httpx.AsyncClient(headers={**headers(), "Last-Event-ID": cursor}, trust_env=False) as http:
                card = await A2ACardResolver(http, url).get_agent_card()
                client = A2AClient(http, agent_card=card)
                request = TaskResubscriptionRequest(id="resume", params=TaskIdParams(id="task"))
                results = [r.model_dump(mode="json")["result"] async for r in client.resubscribe(request)]
                assert [r["metadata"]["agentbridge_sequence"] for r in results] == [1, 2]
                assert recovered.get("alice", "task").sequence == 2
                for invalid in [cursor.rsplit(":", 1)[0] + ":999", "wrong:scope:0"]:
                    response = await http.post(url + "/a2a", json=rpc("tasks/resubscribe"), headers={"Last-Event-ID": invalid})
                    assert response.json()["error"]["code"] == -32602
            await released(app)
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_identity_ownership_errors_and_no_external_cancellation(state, loopback_server):
    tasks, _, headers, factory, _ = state
    with loopback_server(factory) as (url, _):
        async with httpx.AsyncClient(trust_env=False) as http:
            for auth in [{}, headers(expired=True)]:
                assert (await http.post(url + "/a2a", json=rpc(), headers=auth)).status_code == 401
            response = await http.post(url + "/a2a", json=rpc(), headers=headers("bob"))
            assert response.json()["error"]["code"] == -32001
            request = rpc()
            request["params"]["metadata"] = {"owner_id": "alice"}
            assert (await http.post(url + "/a2a", json=request, headers=headers("bob"))).json()["error"]["code"] == -32001
            assert (await http.post(url + "/a2a", json=rpc("tasks/cancel"), headers=headers())).json()["error"]["code"] == -32002
            assert tasks.get("alice", "task").sequence == 0
            assert (await http.post(url + "/a2a", json=rpc("unknown"), headers=headers())).json()["error"]["code"] == -32601
            assert (await http.post(url + "/a2a", json=rpc(id=True), headers=headers())).json()["error"]["code"] == -32600
            assert (await http.post(url + "/a2a", content="{", headers={**headers(), "Content-Type": "application/json"})).json()["error"]["code"] == -32700
            assert (await http.post(url + "/a2a", json=rpc(), headers={**headers(), "A2A-Version": "1.0"})).status_code == 400
            assert (await http.post(url + "/a2a", content=b"x" * 16385,
                                   headers={**headers(), "Content-Type": "application/json"})).status_code == 413


@pytest.mark.asyncio
async def test_capacity_releases_after_disconnect(state, loopback_server):
    tasks, _, headers, factory, _ = state
    limits = StreamLimits(max_streams=1, max_streams_per_owner=1, max_seconds=5, poll_seconds=.01)
    with loopback_server(lambda url: factory(url, limits=limits)) as (url, app):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            async with http.stream("POST", url + "/a2a", json=rpc("tasks/resubscribe")) as response:
                iterator = response.aiter_lines()
                await first_event(response, iterator)
                blocked = await http.post(url + "/a2a", json=rpc("tasks/resubscribe"))
                assert blocked.status_code == 429
            await released(app)
            assert tasks.get("alice", "task").state == TaskState.SUBMITTED


@pytest.mark.asyncio
async def test_deadline_releases_even_when_reader_stops(state, loopback_server):
    tasks, _, headers, factory, _ = state
    limits = StreamLimits(max_seconds=.2, poll_seconds=.01)
    with loopback_server(lambda url: factory(url, limits=limits)) as (url, app):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            async with http.stream("POST", url + "/a2a", json=rpc("tasks/resubscribe")):
                await asyncio.sleep(.5)  # no body consumption at all
                assert app.state.status_streams.total == 0
            assert tasks.get("alice", "task").state == TaskState.SUBMITTED


@pytest.mark.asyncio
async def test_stream_closes_after_authorization_is_revoked(state, monkeypatch, loopback_server):
    _, verifier, headers, factory, _ = state
    with loopback_server(factory) as (url, app):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            async with http.stream("POST", url + "/a2a", json=rpc("tasks/resubscribe")) as response:
                iterator = response.aiter_lines()
                async for line in iterator:
                    if line.startswith("data:"):
                        break
                def revoked(_):
                    raise OidcError("revoked for test")
                monkeypatch.setattr(verifier, "verify", revoked)
                errors = []
                async for line in iterator:
                    if line.startswith("data: "):
                        errors.append(json.loads(line[6:]))
                assert errors[-1]["error"]["code"] == -32000
        await released(app)


@pytest.mark.asyncio
async def test_interrupted_interaction_closes_and_later_work_resumes(state, loopback_server):
    tasks, _, headers, factory, _ = state
    tasks.transition("alice", "task", TaskState.WORKING, expected_sequence=0)
    tasks.transition("alice", "task", TaskState.INPUT_REQUIRED, expected_sequence=1)
    with loopback_server(factory) as (url, app):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            async with http.stream("POST", url + "/a2a", json=rpc("tasks/resubscribe")) as response:
                events, cursor = [], None
                async for line in response.aiter_lines():
                    if line.startswith("id: "):
                        cursor = line[4:]
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:])["result"])
                assert events[-1]["final"] and events[-1]["status"]["state"] == "input-required"
            tasks.transition("alice", "task", TaskState.WORKING, expected_sequence=2)
            tasks.transition("alice", "task", TaskState.COMPLETED, expected_sequence=3)
            async with http.stream("POST", url + "/a2a", json=rpc("tasks/resubscribe"), headers={"Last-Event-ID": cursor}) as response:
                sequences = [json.loads(line[6:])["result"]["metadata"]["agentbridge_sequence"]
                             async for line in response.aiter_lines() if line.startswith("data: ")]
                assert sequences == [3, 4]
        await released(app)

@pytest.mark.asyncio
async def test_message_stream_observes_only_existing_admitted_tasks(state, loopback_server):
    from a2a.types import SendStreamingMessageRequest

    tasks, _, headers, factory, _ = state
    tasks.transition("alice", "task", TaskState.WORKING, expected_sequence=0)
    tasks.transition("alice", "task", TaskState.COMPLETED, expected_sequence=1)
    with loopback_server(factory) as (url, app):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            client = A2AClient(http, agent_card=await A2ACardResolver(http, url).get_agent_card())
            message = Message(message_id="stream", role=Role.user, task_id="task",
                              parts=[Part(root=TextPart(text="observe status"))])
            request = SendStreamingMessageRequest(id="stream", params=MessageSendParams(message=message))
            results = [r.model_dump(mode="json")["result"] async for r in client.send_message_streaming(request)]
            assert [r["metadata"]["agentbridge_sequence"] for r in results] == [0, 1, 2]
            wire = request.model_dump(mode="json", exclude_none=True)
            del wire["params"]["message"]["taskId"]
            assert (await http.post(url + "/a2a", json=wire)).json()["error"]["code"] == -32004
            wire["params"]["message"]["taskId"] = "task"
            wire["params"]["message"]["parts"] = [{"kind": "data", "data": {"name": "delete"}}]
            assert (await http.post(url + "/a2a", json=wire)).json()["error"]["code"] == -32005
            assert tasks.get("alice", "task").sequence == 2
        await released(app)


@pytest.mark.asyncio
async def test_cursor_cannot_cross_owner_even_with_same_task_id(state, loopback_server):
    tasks, _, headers, factory, _ = state
    tasks.create("bob", TaskLifecycle("task", "other-context", "a2a"))
    with loopback_server(factory) as (url, app):
        async with httpx.AsyncClient(trust_env=False) as http:
            async with http.stream("POST", url + "/a2a", json=rpc("tasks/resubscribe"), headers=headers()) as response:
                cursor, _ = await first_event(response)
            await released(app)
            response = await http.post(url + "/a2a", json=rpc("tasks/resubscribe"),
                                       headers={**headers("bob"), "Last-Event-ID": cursor})
            assert response.json()["error"]["code"] == -32602
            response = await http.post(url + "/a2a", json=rpc(), headers=headers("bob"))
            assert response.json()["result"]["contextId"] == "other-context"


@pytest.mark.asyncio
async def test_asgi_backpressure_deadline_releases_connection():
    from src.serve.a2a_status import _BoundedStreamingResponse

    released_slots = []
    async def body():
        yield b"data: synthetic\n\n"
    async def blocked_send(message):
        if message["type"] == "http.response.body":
            await asyncio.Future()
    async def receive():
        await asyncio.Future()
    response = _BoundedStreamingResponse(body(), max_seconds=.05,
                                         release=lambda: released_slots.append(True))
    started = time.monotonic()
    await asyncio.wait_for(response({"type": "http", "asgi": {"spec_version": "2.4"}},
                                    receive, blocked_send), timeout=1)
    assert time.monotonic() - started < 1 and released_slots


def test_service_rejects_untrusted_transport_configuration(state):
    tasks, verifier, _, _, _ = state
    for origin in ["http://remote.example", "https://user:secret@trusted.example", "https://trusted.example/path"]:
        with pytest.raises(ValueError):
            create_a2a_status_app(tasks, verifier, public_url=origin)
    for options in [{"max_streams": True}, {"max_seconds": float("inf")}, {"page_size": 101}]:
        with pytest.raises(ValueError):
            StreamLimits(**options)



@pytest.mark.asyncio
async def test_accept_negotiation_and_nonfinite_json_rejected(state, loopback_server):
    _, _, headers, factory, _ = state
    with loopback_server(factory) as (url, _):
        async with httpx.AsyncClient(headers=headers(), trust_env=False) as http:
            response = await http.post(url + "/a2a", json=rpc("tasks/resubscribe"),
                headers={"Accept": "*/*;q=1, text/event-stream;q=0"})
            assert response.status_code == 406
            response = await http.post(url + "/a2a", content='{"jsonrpc":"2.0","id":1,"method":"tasks/get","params":{"id":"task","metadata":{"bad":NaN}}}',
                                      headers={"Content-Type": "application/json"})
            assert response.json()["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_slow_request_body_cannot_hold_the_handler(state, loopback_server):
    from urllib.parse import urlsplit

    _, _, headers, factory, _ = state
    limits = StreamLimits(request_seconds=.05)
    with loopback_server(lambda url: factory(url, limits=limits)) as (url, _):
        target = urlsplit(url)
        reader, writer = await asyncio.open_connection(target.hostname, target.port)
        try:
            wire = ("POST /a2a HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: " +
                    headers()["Authorization"] + "\r\nContent-Type: application/json\r\n" +
                    "Transfer-Encoding: chunked\r\n\r\n1\r\n{\r\n")
            writer.write(wire.encode())
            await writer.drain()
            response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
            assert response.startswith(b"HTTP/1.1 408")
        finally:
            writer.close()
            await writer.wait_closed()
