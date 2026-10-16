# Atomic local admission

For gateway participants sharing one durable SQL store, admission commits the
operation claim, budget reservation, reservation link and required one-shot
approval consumption together. Tenant composition requires that shared store
and a request-bound durable operation ID. Caller-owned legacy embeddings using
separate or in-memory participants retain their weaker accounting contract.

Supported protocol translation is pure preparation and occurs before these
mutations. Unsupported semantics therefore fail before a reservation or grant
is consumed. The gateway checks authorization, claims/locks the operation before
budget, reserves exposure, links the owned token, consumes any required approval
and rechecks current authority before committing. Invocation starts only after
admission returns successfully. Local transaction order matches outcome
settlement and reconciliation.

A process dying before admission commit leaves the original approval available,
no new operation claim and no orphaned reservation. A policy/race rejection
rolls back its partial state, then records its denial outside the aborted
transaction. A reservation cannot be attached to another agent, two operations,
an already bound operation or a terminal operation.

After a confirmed commit, a crash before or during dispatch leaves a durable
UNKNOWN claim with its reservation and consumed grant. The gateway does not
automatically execute that operation again. An uncertain SQL commit acknowledgment
also requires inspecting durable state: a remote effect is never inferred from
local bookkeeping. Exact commit-ACK-loss/partition qualification remains a
separate recovery task; these tests establish pre-commit rollback and ordinary
commit visibility.

Qualification exercises actual worker-process termination after reservation,
approval consumption and claim on SQLite and PostgreSQL. Signed tenant-session
tests cover grant rollback, denial-audit persistence and separate-connection
invisibility of partial state. Existing body/signature/revocation, duplicate
admission, cancellation and settlement tests must continue to pass at the exact
reviewed commit.

This does not add durable executable task payloads, aggregate tenant/user quotas,
safe retention or authoritative tenant-aware outcome reconciliation. Those remain
subsequent engineering work. It does not establish independent custody or
unrestricted production acceptance; the production target restriction remains.
