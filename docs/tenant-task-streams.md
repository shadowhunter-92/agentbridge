# Tenant task status streams

The opt-in multi-tenant control plane exposes `POST /v2/tasks/stream` for observing an existing durable task. This is a tenant-native SSE projection. It does not execute, retry, resume, cancel, or settle a task or an external operation, and it does not claim A2A protocol conformance. Trusted workers still own task creation and transitions.

## Request and replay

Send a signed JSON body with the usual tenant agent authentication headers (`x-tenant-id`, `x-agent-id`, `x-nonce`, `x-signature`, and `x-delegation-id` when delegated):

```json
{"request_scope":"task.stream","task_id":"existing-task-id","after_sequence":-1}
```

The content type must be `application/json`; `Accept` must permit `text/event-stream`. The body is strict: unknown fields, duplicate JSON members, non-integer cursors, cursors below `-1`, and cursors at or above `2**63` fail validation. A cursor beyond the current task sequence returns 400. Sign the exact task ID and cursor in the body. A new request needs a fresh signed nonce, including on reconnect. Query parameters and `Last-Event-ID` do not replace the signed cursor.

Each event has an integer `id` equal to its durable sequence and a JSON `data` object containing the durable task snapshot. Replay returns sequences strictly after `after_sequence`; `-1` starts at the first retained event. The integer is meaningful only within the requested task and exact authenticated owner scope. It is not a transferable or globally unique cursor. A browser's native `EventSource` does not issue this signed POST; use an SSE-capable POST client.

The kernel enforces the tenant, agent, human delegation, capabilities, and target scope of the original task owner. A different tenant, agent, narrower grant, or machine/delegated identity cannot inherit another scope's history. A replacement grant with the same stable human, agent, and exact scopes can observe the same history. A missing or inaccessible task returns 403.

The stream closes after a terminal state, `input-required`, `auth-required`, its bounded lifetime, disconnect, failed authorization, lost allocation, SQL error, or stalled send. A close is not evidence of a successful or failed external effect. Reconnect with the last event actually consumed and inspect existing state. If the signed cursor already consumed the current terminal or waiting state, the response closes without heartbeats. A newer event observed after an empty page is still replayed. Failures before response headers use the normal HTTP error handlers; a response already started closes without changing its status. No closure invents a terminal task transition or releases an execution reservation.

## Shared allocation limits

`create_tenant_app(kernel, stream_limits=StreamLimits(...), fleet_stream_limits=FleetStreamLimits(...))` accepts trusted operator configuration. All coordinated replicas must use the same authority database and namespace and the same fleet policy. Separate authority databases are separate coordination domains. PostgreSQL supports shared replicas; SQLite coordination requires access to the same local database file and its locking guarantees.

| Fleet setting | Default | Meaning |
| --- | ---: | --- |
| `max_streams` | 64 | Active authorized allocations across this coordination domain |
| `max_per_tenant` | 16 | Active allocations for one tenant across owners and replicas |
| `max_per_owner` | 4 | Active allocations for one stable human or machine owner |
| `lease_seconds` | 5 | Renewable allocation lifetime using database wall time |
| `max_seconds` | 60 | Absolute allocation lifetime; renewals never extend it |

The owner key includes tenant, identity kind, issuer, and subject. A human's replacement grants, different scopes, and different delegated agents share that human's owner limit. Exact task visibility still uses the narrower resource owner key. The machine agent's own identity has a separate owner allocation from its delegated human.

The existing process-local `_Streams` limits also apply (`StreamLimits.max_streams` and `max_streams_per_owner`, defaults 64 and 4). Admission must pass both local and shared limits. Capacity exhaustion returns 429 with `Retry-After: 1`. A failed shared admission releases the local slot. If a request is cancelled while SQL admission continues in a thread, retained cleanup releases its eventual allocation when that thread completes; expiry is the fallback for worker death or unavailable cleanup.

Capacity integers must be between 1 and 10,000. Fleet lease time must be between 0.05 and 30 seconds, absolute lifetime between 0.05 and 3,600 seconds, and the lease must fit that lifetime. Booleans and nonfinite timings are rejected. Local polling must fit within one third of the fleet lease. The actual response lifetime is the smaller local and fleet lifetime. Each ASGI send is bounded by the smaller of one second and half the lease interval.

**These are active authorized allocation limits. A frontdoor hard connection cap is still required.** A paused or partitioned worker may retain a physical TCP socket after its allocation expires. A bounded database allocation cannot close that socket or retract bytes already accepted by the network. Configure connection counts, timeouts, TLS, and request rate/body limits at the ingress. This endpoint does not coordinate the separate legacy `/a2a` status endpoint; that endpoint retains its existing process-local limits.

## Fencing and operation

Every response-header and body send, including each chunk from an already fetched page and heartbeat, rechecks current authority and renews the exact opaque allocation. Quiet polling also renews without requiring new task events. Agent/grant/member/tenant revocation, expired principal consent, expired allocation, released allocation, or unsupported policy stops later sends. No SQL/authority lock is held across network sends. Revocation between the last check and the network send cannot retract that in-flight chunk.

Expired or released allocations cannot renew. A new admission removes expired ephemeral allocation rows and receives a new random identity. An old worker resuming afterward cannot renew or delete its replacement. Disconnect and bounded send/lifetime completion release local and durable capacity; actual worker death recovers shared capacity through expiry. Task history, audit evidence, and operation outcome records are not deleted by allocation cleanup.

Fleet policy is persisted at first initialization. Different replica limits, an unsupported version, a missing policy row, a partial schema, or a view in place of an ordinary coordination table fails closed. Running replicas recheck policy on acquisition, renewal, and usage. Operators must coordinate policy changes; editing configuration on one live replica does not migrate the persisted policy.

Database wall time determines allocation expiry, while response deadlines use process monotonic time and authentication retains its existing clock assumptions. Keep database and worker clocks synchronized and account for pauses, database latency, and scheduling delays when choosing the lease. A worker that misses its lease must reconnect, even if it believes its socket is still usable.

Preserve `stream_lease_policy_v1` and `stream_leases_v1` in authority backups. Stop and drain all workers and close their ingress connections before restoring or replacing the authority database; restore it consistently with the tenant task/authority state. Restoring an earlier snapshot can resurrect obsolete allocations or omit current allocations. An entirely absent pair of tables is treated as first initialization, so deleting both is not a supported live reset. This feature cannot fence old processes across an uncoordinated database rollback or independent authority clones. Reviewed recovery and deployment coordination remain operator responsibilities.
