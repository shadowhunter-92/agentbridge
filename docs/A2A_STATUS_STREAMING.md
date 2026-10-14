# Authenticated A2A task-status streaming — qualified subset

This opt-in factory projects tasks that trusted workers already admitted through
the SQL lifecycle SDK. It is not enabled by the default control-plane CLI and
does not automatically create/link tasks from existing HTTP action requests.
The embedding application owns governed admission, operation/task correlation,
worker publication and SQL-handle shutdown. Network messages cannot create a
task, dispatch/retry a tool, settle a budget, or cancel an external action.

Install `.[a2a]` for the reviewed A2A SDK 0.3.26 family. The public wire contract is
[A2A 0.3 JSON-RPC](https://a2a-protocol.org/v0.3.0/specification/), not A2A 1.x.
Pin `requirements-protocols.txt` for the network qualification environment.

## Embedding

```python
import os
from src.api.auth_oidc import OidcConfig, OidcVerifier
from src.governance.store import make_store
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.serve.a2a_status import create_a2a_status_app

store = make_store(os.environ["AGENTBRIDGE_DB"])
tasks = DurableTaskLifecycle(store)
verifier = OidcVerifier(OidcConfig(
    issuer=os.environ["AGENTBRIDGE_OIDC_ISSUER"],
    audience=os.environ["AGENTBRIDGE_OIDC_AUDIENCE"],
))
app = create_a2a_status_app(tasks, verifier,
    public_url=os.environ["AGENTBRIDGE_STATUS_PUBLIC_URL"])
```

Serve this ASGI app behind independently configured TLS. HTTPS public origin,
trusted HTTPS issuer and explicit audience are required. Loopback HTTP needs the
explicit `allow_loopback_http=True` evaluation option. The factory cannot verify
an external reverse proxy's TLS, access policy or network isolation for you.

A verified JWT `sub` from the configured issuer/audience is the SDK owner_id.
Trusted workers must use that exact owner mapping. Request metadata, task fields,
custom headers and administrator keys cannot choose another owner. The public
AgentCard is at `/.well-known/agent-card.json`; authenticated RPC is at `/a2a`.

## Supported behavior

| Method | Status-observer behavior |
| --- | --- |
| tasks/get | Return the authenticated owner's existing Task snapshot |
| message/send | A text status query with an existing message.taskId returns that snapshot |
| message/stream | The same existing-task query opens an SSE status stream |
| tasks/resubscribe | Replay observed task history using the optional cursor, then follow new updates |
| tasks/cancel | Return TaskNotCancelable; observation cannot promise external cancellation |
| Other procedures, new task submission, data/tool parts, message configuration | Explicit errors; no fallback execution |

SSE data contains SDK-validated JSON-RPC Task/status-update responses. The first
unseen event is a Task snapshot, followed by status updates in durable sequence
order. Terminal or input/auth-required interactions close the stream. The API
intentionally has no artifact delivery, push notifications, new execution path,
task mutation endpoint, billing response or implicit retry.

Each event has an `id` cursor bound to its owner and task. Reconnect with that
exact last consumed `Last-Event-ID`. The cursor is a documented AgentBridge
extension, not an A2A-standard replay guarantee or tamper-proof audit anchor.
Future/malformed/cross-owner cursors are denied. If an interaction has already
ended and no event remains beyond the cursor, the observer returns an explicit
unsupported-operation response rather than inventing another state update.

## Bounds and identity lifetime

Defaults: 16 KiB request body, 16 events per fetched page, 64 simultaneous streams
per application process, four per owner, a five-second request-body deadline,
60-second stream deadline and bounded polling. Capacity returns HTTP 429. The deadline covers ASGI backpressure;
disconnect, timeout and completion release the connection slot without changing
task or operation state. Load balancers should disable SSE buffering and use
timeouts compatible with the configured stream lifetime.

JWT verification repeats before each fetched page. Expired or now-rejected tokens
close the stream. Removed JWKS keys follow the configured cache TTL/cooldown;
there is no newly added IdP introspection or per-user session-revocation service.
Immediate account revocation and operated workload identity remain explicit
deployment/next-phase requirements. These process limits are not fleet-wide
tenant quotas. Total historical-task retention and legal hold remain separate.

## Qualification and remaining scope

Real loopback HTTP tests use the official A2A 0.3 SDK client, JWT signatures,
SQLite/PostgreSQL handles, server restart, disconnect/replay, owner separation,
cursor tampering, rejected credentials, interrupted interactions, body/version
errors, capacity and blocked-send deadlines. The compatibility SDK client used
for existing 0.3 behavior is deprecated upstream; migration belongs to the
explicit A2A-version/client upgrade, not a silent conformance claim.

Full A2A conformance, A2A 1.x, governed async action admission/cancellation,
artifacts, external notifications, service tenant isolation and production HA
are not established by this observer. See [execution plan](EXECUTION_PLAN_2026-10-14.md).
