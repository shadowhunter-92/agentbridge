# Durable task event-byte capacity — October 16, 2026

Baseline: `4892b37a72a6a11a346fe5b3347d708bf26e226e` (PR #67).
Historical task count and per-task event count do not bound aggregate event bytes.

The existing lifecycle now accounts actual UTF-8 bytes in retained event snapshots
across every owner in a SQL namespace. The default is 64 MiB, explicitly
configurable from 4 KiB to 1 GiB. A limit of 4 KiB admits no new task because it
cannot cover initial status plus required control-event headroom. No automatic
history deletion, refund, task execution or UNKNOWN resolution is introduced.

Each supported canonical status snapshot is bounded to 4 KiB. Tests cover maximum
128-character non-BMP task/context identifiers and the maximum supported sequence.
Submitted/working tasks reserve 8 KiB: one input/authentication-required waiting
status and one terminal status. A waiting task retains 4 KiB for termination.
Resuming to working must replenish the 8 KiB reservation as well as pay for its
event; saturation leaves the prior waiting state intact. This is byte capacity,
not permission to bypass the separate per-task event-count limit or transition
state machine. A future execution service must qualify its required event slots.

Policy and metadata use a new versioned table pair, preserving the already
qualified history-cap schema. Both absent is a transactional first introduction;
one absent, missing rows, wrong relation kinds or unknown versions fail closed.
Existing history plus required reservations must fit at introduction. A trusted
operator can provide `initial_max_event_bytes` for reviewed larger historical
state; it cannot override an existing policy. A failed introduction rolls back
schema creation and leaves task/event bytes unchanged. Deleting both tables or
guards with database-owner credentials is outside the application trust boundary.

The SDK's create/transition, byte-policy change and administrative audit use the
existing SQL boundary and task advisory lock. Private tenant namespaces also
install SQL INSERT guards for supported older worker paths. The guards account
the older event-before-snapshot-update ordering, reserve only the matched task's
control space, and recheck after real PostgreSQL contention. Reads are qualified
to the private schema with invoker rights and `search_path=pg_catalog`. Existing
tenant write guards protect new policy tables immediately. Standalone legacy
stores retain application-level bounds and ordinary-table migration scope.

Actual SUM bytes are the accounting source, avoiding a separately driftable
counter. This scans stored history and is not a large-history performance/SLO
claim. Direct owner-level UPDATE/DELETE/DDL, forged application code and arbitrary
malformed SQL rows are not authenticated ingress. No storage-size claim includes
indexes, database WAL, snapshot copies, audit/evidence blobs or network streams;
those remain separately accounted requirements.

`TenantSession.task_event_capacity` requires budget-read permission and returns
`max_event_bytes`, `used_event_bytes`, `reserved_control_bytes`.
`set_task_event_capacity` requires policy-write permission and an exclusive
authority guard; policy and audit commit together. A decrease below retained
bytes plus reservations is rejected. HTTP GET/PUT
`/v2/operator/task-event-capacity` accepts strict body
`{"max_event_bytes": 67108864}` using the same tenant/operator authority.

Positive/negative tests cover UTF-8 accounting, saturation and recovery/terminal
headroom, restart, competing replicas, older SQL workers, actual PostgreSQL
blocking, damaged metadata, prior-schema introduction/rollback, process death
after terminal-event insertion, cross-tenant access, operator permissions and
audit rollback. Exact local/CI evidence belongs in the phase report.

Status persistence remains distinct from executable async tasks, acknowledged
destination cancellation and independently verified external effects. Fleet
stream leases, audit/evidence bounds, protected retention, network/HA/release and
full-path performance remain separate. Unrestricted production remains NO-GO.
