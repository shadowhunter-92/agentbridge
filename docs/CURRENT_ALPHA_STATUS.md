# Current engineering alpha status — October 17, 2026

**Overall: PARTIALLY TESTED; unrestricted consequential-action production NO-GO.**
This is the current documentation entry point for the recorded source snapshot.
It supersedes present-tense status, pending-work and branch-count statements in
older reports; it does not change their original results or authorize a merge,
release, deployment or deletion. Apache 2.0 remains in force.

## Source and artifact pins

| Item | Exact pin | Meaning |
| --- | --- | --- |
| Recorded main | `73aafd60a0eec121a10245a307a4a8ee268f7ed5` | Main baseline, before the tenant draft stack |
| Cumulative draft source | `46777f8c953690fca81c6d11e7b70372b8dd5c77` | PR #69 plus dependencies #56–#68; recorded as draft/unmerged |
| Local evaluator source | `d0881b937d2568e4e01fb02044bf466aea609e9a` | Older PR #63 source used for the separate local wheel |
| Recorded local evaluator wheel SHA-256 | `2367045ebfbe0fa502d4f8f59183696181834a847d2d309f1894e48667deb703` | Local, unsigned, unpublished; not built from `46777f8` |

The main badge, package version `1.0.0`, source installation and local wheel
are different evidence. None establishes a signed public artifact or an
independent evaluation. Use Python 3.11/3.12 and record the exact selected SHA.
[Evaluator instructions](OSS_EVALUATION_KIT.md) retain their older artifact pin.

## Cumulative draft dependencies and recorded CI

The October 17 read-only inventory records 19 remote heads and 14 open draft,
unmerged PRs, #56–#69. Main remains at the separate baseline above. Locally
retained hosted-check receipts record 24 successful checks at each head below.
PR #69's exact-head receipt records 7 successful workflows / 24 jobs, including
[CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/38991859193),
[Trust/Evidence](https://github.com/shadowhunter-92/agentbridge/actions/runs/38991859007),
[inline protocols](https://github.com/shadowhunter-92/agentbridge/actions/runs/38991859072)
and [disposable CNI acceptance](https://github.com/shadowhunter-92/agentbridge/actions/runs/38991859150).
These are recorded exact-head results, not evidence that this later local
documentation correction passed CI, a security approval or a merge approval.
Refresh PR state, protections and checks on the actual proposed integration
head before a merge.

| Draft PR | Source head | Bounded unit |
| --- | --- | --- |
| #56 | `423a6893e6c77a8212f8a1fe37d5e91c8745db04` | [Enrolled authority](TENANT_AUTHORITY_FOUNDATION_2026-10-14.md) |
| #57 | `10393374e1cb05778b70eb5ddde65d343ff79a50` | [Tenant runtime and HTTP](TENANT_RUNTIME_2026-10-14.md) |
| #58 | `51e3f4c6f9c85371ec0a2339b312f78823b26a40` | [Offline historical assignment](TENANT_MIGRATION_2026-10-14.md) |
| #59 | `f2629d2baf23ff83cbbe7c43dc7257c63639cc93` | [Atomic settlement](ATOMIC_GOVERNANCE_STATE_2026-10-14.md) |
| #60 | `23b3d00413f4331ea949edc70560d2d9962eefe7` | [Atomic admission](ATOMIC_ADMISSION_2026-10-14.md) |
| #61 | `7ee8252c814c4f9e4f20440951eac4a00938757d` | [Aggregate admission quotas](DURABLE_ADMISSION_QUOTAS_2026-10-15.md) |
| #62 | `228398ca9a0d95d49b4fbea9d0468998e1a10ff7` | [PostgreSQL namespace checks](TENANT_POSTGRES_NAMESPACE_CHECKS_2026-10-16.md) |
| #63 | `d0881b937d2568e4e01fb02044bf466aea609e9a` | [Tenant signing coordination](TENANT_SIGNING_COORDINATION_2026-10-16.md) |
| #64 | `eb2dcea8d722def931b95f15a8767d2592c54ad6` | [Task SQL/authority composition](TASK_ATOMIC_SCOPE_2026-10-16.md) |
| #65 | `8ab8ff3c16d3859a6ff86ea4e66154332fa2d1e4` | [SQLite component savepoints](SQLITE_ATOMIC_MUTATIONS_2026-10-16.md) |
| #66 | `573826fcb29039e9438ea5a8746a21faf9f7b409` | [Policy publication](TENANT_POLICY_PUBLICATION_2026-10-16.md) |
| #67 | `4892b37a72a6a11a346fe5b3347d708bf26e226e` | [Retained-task count](TASK_HISTORY_CAPACITY_2026-10-16.md) |
| #68 | `07303af24857322c59c02977dbcca67d74e91d8f` | [Retained event bytes](TASK_EVENT_CAPACITY_2026-10-16.md) |
| #69 | `46777f8c953690fca81c6d11e7b70372b8dd5c77` | [Tenant-native status streams and shared allocations](tenant-task-streams.md) |

These heads form a cumulative dependency chain. Compare the whole proposed
main-to-head diff; a later head includes earlier source but does not turn an
earlier scan or test run into a full review of later additions. The historical
[88-row handoff register](HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md) remains the
original requirement record, with its phase-specific values preserved.

## Implemented boundaries and open requirements

The opt-in `TenantKernel`/`create_tenant_app` path uses enrolled authority and
private tenant SQL namespaces. It does not automatically tenant-enable legacy
HTTP, CLI, MCP or A2A entry points. The current tenant HTTP API is explicitly
constructed by trusted setup; general CLI configuration loading remains open.

When governance participants share one durable SQL store, gateway admission
commits claim, quota attribution, reservation link and approval consumption
together. Definite settlement and pre-invocation abort compose local budget,
operation and audit changes. Separate/in-memory legacy participants retain a
weaker contract. This local accounting cannot roll back a remote effect;
UNKNOWN retains exposure and is not automatically replayed or refunded.

| Area | Implemented in the cumulative draft | Still open |
| --- | --- | --- |
| Admission | Operator-enabled tenant/human spend, admission-rate and active-operation caps, durable attribution | Frontdoor shedding/rate limits, authentication storage bounds, custom per-user limits and large-history performance |
| Task history | Namespace-wide retained count, default 10,000; terminal history included | Safe protected cleanup/retention and capacity sizing |
| Task event bytes | Actual retained UTF-8 snapshot bytes, default 64 MiB; bounded recovery/terminal reservations | Audit/evidence bytes, indexes/WAL/copies and large-history contention |
| Task lifecycle | Durable owner-scoped non-executable status, events, compare-and-update and replay | Authorized executable intent linked to operations, worker recovery and acknowledged destination cancellation |
| Tenant status streams | Signed existing-task/cursor observation; shared authority-database allocation caps, defaults 64 fleet / 16 tenant / 4 stable owner; 5-second lease and 60-second absolute lifetime | Frontdoor physical connection/rate/body limits, contention/resource qualification and coordinated stop/drain/restore; legacy `/a2a` limits remain process-local |
| Migration | Bounded offline ordinary-table assignment and conservative rollback | Large databases, rolling/live workload migration and active-work rollback |
| Tenant coverage | Selected enrolled SDK/HTTP operations, namespace checks and operator policies | Complete evidence, reconciliation, background-service and protocol network coverage |
| Protocols | Six adapter families' basic call subset; bounded official SDK loopback MCP HTTP and A2A 0.3 status observation | Full version/transport/lifecycle matrix, A2A 1.x, newer MCP support, artifacts/push/OAuth and general resumability |
| Operations | Reference fencing/readback, recovery tests and deployment references | Actual destination enforcement, combined workload identity/operated network isolation, automated HA, full-path SLOs and trusted release provenance |

Capacity guards do not make database owners, arbitrary DDL or trusted in-process
code untrusted. Supported older tenant INSERT paths have the documented SQL
guards; this is not general rolling-version compatibility. Per-owner active and
per-task event-count configuration still must match replicas. Event-count and
state-machine limits remain independent of byte headroom. No capacity feature
deletes UNKNOWN state, reservations or held evidence to regain room.

The stream unit is **VERIFIED IN CI for active authorized allocations only**.
The recorded final local SQLite/PostgreSQL regression had 228 passed and 2
SQLite-only skips for PostgreSQL trigger-visibility checks; the PostgreSQL cases
ran. Local JUnit did not embed a contemporaneous Git head; a later source/blob
association ties the six feature files to the final source. Stream observation
does not create an executable task, invoke a worker, retry, resume execution,
cancel an external effect, settle/refund a reservation or resolve UNKNOWN.
A paused/partitioned worker can retain a physical socket after its allocation
expires. Separate authority databases do not share a fleet limit. Uncoordinated
restore/clones can resurrect or omit allocations; reviewed stop/drain and
consistent authority/task recovery remain required.

The [generic production target restriction](PRODUCTION_TARGET_QUALIFICATION_2026-10-14.md)
still applies, including standalone remote MCP tools. A signature authenticates
its signer's statement; authoritative independent readback and custody must be
established separately. No universal exactly-once, full protocol conformance,
regulatory compliance or production certification is claimed.

Independent security acceptance, three unrelated returned developer evaluations,
five qualified buyer interviews, separately administered destination/signer/
observer/retention custody and a supervised written pilot remain unaccepted.
Internal CI, invitations and local demonstrations do not close these gates.

## Documentation and branch disposition

Use [the index](README.md), [roadmap](ROADMAP.md) and the bounded unit documents
above for the current source. Dated AWS, audit, branch, execution and handoff
reports retain their exact historical results. Their older future-work lists do
not override this page or broaden the source's supported contract.

[Branch documentation dispositions](BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md)
records the October 17 remote inventory, the older cached comparison and
historical cleanup separately. Updating this local documentation branch does not
rewrite maintained or historical branch heads. Local unpublished work after the
source pin is outside this page's tested source scope.
