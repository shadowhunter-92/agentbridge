# Current engineering alpha status — October 22, 2026

**Overall: PARTIALLY TESTED; unrestricted consequential-action production NO-GO.**
This is the current documentation entry point for the recorded source snapshot.
It supersedes present-tense status, pending-work and branch-count statements in
older reports; it does not change their original results or authorize a merge,
release, deployment or deletion. Apache 2.0 remains in force.

## Source and artifact pins

| Item | Exact pin | Meaning |
| --- | --- | --- |
| Recorded main | `b0afb7f1da1634330747389e19c896fd7002bd83` | Approved PR #70 merge; exact main CI 16/16 passed |
| Reviewed audit/admission source | `7415718eef8b9650875885ab17eb4d15acf3489b` | Merged as the second parent; identical tree; separate source CI 24 jobs / seven workflows |
| Private dispatch follow-up | Select this follow-up’s exact Git head | Local source-pinned functional qualification; consult that head’s hosted checks independently |
| Cumulative draft source | `46777f8c953690fca81c6d11e7b70372b8dd5c77` | PR #69 plus dependencies #56–#68; recorded as draft/unmerged |
| Queued-acceptance follow-up source | `de1194a0b568c820205ac0abaa7f774eb530ae83` | Native queued intent plus documentation integration; seven successful workflows / 24 jobs recorded, queued acceptance only |
| Private preparation follow-up source | `893fdba4d3d1928bd66491affcb87e01a263b063` | Draft PR #70; seven successful workflows / 24 jobs recorded, preparation without admission or execution |
| Private atomic-admission follow-up source | `08355255ee3fc96461d3d33942cb8f730e8d924b` | Draft PR #70; seven successful workflows / 24 jobs, private admission and task/operation/event linkage without dispatch |
| Local evaluator source | `d0881b937d2568e4e01fb02044bf466aea609e9a` | Older PR #63 source used for the separate local wheel |
| Recorded local evaluator wheel SHA-256 | `2367045ebfbe0fa502d4f8f59183696181834a847d2d309f1894e48667deb703` | Local, unsigned, unpublished; not built from `46777f8` |

The main badge, package version `1.0.0`, source installation and local wheel
are different evidence. None establishes a signed public artifact or an
independent evaluation. Use Python 3.11/3.12 and record the exact selected SHA.
[Evaluator instructions](OSS_EVALUATION_KIT.md) retain their older artifact pin.
The queued-intent source pin includes source `01376a59f13e7c4104ff0d2c507473ae334a9422`
and the subsequent reviewed documentation integration. Record the actual selected
Git head and its own CI evidence. Private first-admission/linkage has its own
`08355255` results, separate from queued-acceptance and preparation CI. The
audit-capacity follow-up described below is later source and requires its own
selected-head evidence; it is not covered by the admission head's checks.

## Current merge and historical dependency evidence

On October 22, the owner approved marking PR #70 ready and merging its exact
`7415718` head with a merge commit. Main `b0afb7f` has the same source tree and
passed all 16 jobs in [CI run 39736688053](https://github.com/shadowhunter-92/agentbridge/actions/runs/39736688053).
GitHub marked dependency PRs #56–#69 merged. After a separately restored
20-head backup and fresh SHA/protection/PR/ancestry checks, the approved
14 redundant refs were deleted atomically; six maintained or active refs remain.
See [consolidation evidence](BRANCH_CONSOLIDATION_2026-10-22.md).

The dated inventories and source pins below are historical: “draft/unmerged”
describes their original observation, not the current PR state. Source CI is
not relabeled as an execution against the merge commit or this later follow-up.

The October 17 read-only inventory records 19 remote heads and 14 open draft,
unmerged PRs, #56–#69. Main was then `73aafd60`. Locally
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
The later queued-intent and documentation continuation is outside that frozen
inventory; the table below preserves its original heads rather than implying
that later branches were part of the query.
The separate October 18 post-preparation inventory records 20 remote heads and
15 open draft/unmerged PRs, #56–#70, with PR #70 at `893fdba`. That head's seven
successful workflows / 24 jobs include
[CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/39116757207).
The October 20 inventory also records 20 remote heads and 15 open draft PRs,
with PR #70 advanced to `08355255`; all 20 recorded heads were ancestors of it.
Its seven workflows / 24 jobs passed, including
[CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/39399999492).
The October 21 read-only PR refresh still recorded that head, open/draft and
unmerged. These inventories do not authorize consolidation or qualify later
changes. Refresh the actual proposed head and current PR state.

| Historical PR | Original source head | Bounded unit |
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

| Area | Implemented in maintained source / selected follow-up | Still open |
| --- | --- | --- |
| Admission | Operator-enabled tenant/human spend, admission-rate and active-operation caps, durable attribution | Frontdoor shedding/rate limits, authentication storage bounds, custom per-user limits and large-history performance |
| Task history | Namespace-wide retained count, default 10,000; terminal history included | Safe protected cleanup/retention and capacity sizing |
| Task event bytes | Actual retained UTF-8 snapshot bytes, default 64 MiB; bounded recovery/terminal reservations | Remaining evidence bytes, indexes/WAL/copies and large-history contention |
| Audit payload capacity | SQL-trigger row/UTF-8 byte/per-entry limits, persisted counters and conservative store-API retention refusal | Remaining evidence journals/checkpoints, reference-indexed retention, mixed-version operation, independent custody and sustained performance |
| Task lifecycle | Durable owner-scoped status/events, signed intent and atomic linkage; private one-shot synthetic dispatch, result/settlement and read-only recovery in this follow-up | Public worker and arbitrary network destination; historical-key recovery; authoritative failure/absence proof and acknowledged destination cancellation |
| Queued intent capacity | Immutable provenance, default 64 KiB intent / 64 KiB result allowance / 1,024 retained intents / 128 MiB aggregate, plus existing lifecycle bounds; private immutable result writer in this follow-up | Public result delivery, protected retention and sustained resource qualification; unused result headroom is not a result payload |
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

## Selected private dispatch follow-up

The [bounded dispatch and recovery unit](QUEUED_DISPATCH_AND_RECOVERY_2026-10-22.md)
is **PARTIALLY TESTED** locally against frozen runtime/test bytes on the merged
baseline. One final run recorded 861 distinct cases: 830 passed and 31 expected
SQLite skips of PostgreSQL-only tests. The seven new modules contain 309 cases
(288 passed, 21 skipped), including 34 passing real PostgreSQL variants; shared
regressions contain 552 cases (542 passed, 10 skipped). Overlapping older runs
are retained separately. These results do not qualify a public service or a
production transport; selected-head hosted evidence remains separate.

The private worker commits an immutable one-shot attempt before any effect and
only that live branch may send. A restart, dropped return or existing marker
permits read-only reconciliation, never automatic resend. Authoritative success
binds the exact result and original reservation in the same local settlement
transaction. Missing/mismatched evidence or failed local recording preserves
UNKNOWN and exposure. The destination is an explicitly nonproduction SQLite
`write(value)` demonstration, including when tenant accounting uses PostgreSQL.
Current manual settlement authority is held/rechecked through the actual commit.

Pre-attempt cancellation can close the attempt and refund its exact held token;
after an attempt it records only a bounded cancellation request. No remote
cancellation acknowledgment or authoritative absence/refund protocol is claimed.
Current descriptor/pin rotation can leave old attempts unresolved. A public
worker/poller, generic network dispatch and production qualification remain open.

The earlier unit descriptions below retain their original boundaries; their
then-future private dispatch/result work is superseded only by this follow-up.

The stream unit is **VERIFIED IN CI for active authorized allocations only**.
The [queued-intent follow-up](TENANT_TASK_INTENTS_2026-10-17.md) is
**VERIFIED IN CI for queued acceptance only** at
`de1194a0b568c820205ac0abaa7f774eb530ae83`: seven workflows / 24 jobs succeeded,
including [CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/39013120802).
Its earlier corrected-source local affected regression passed 151 tests
with one expected SQLite skip of a PostgreSQL-only test. Ten retained pre-fix
HTTP reproductions failed as expected; the corrected API/replica cases passed
14 tests. These overlapping local receipts remain separate. Acceptance commits immutable intent, SUBMITTED
status/event and audit only. It claims no operation, reserves no budget,
consumes no approval and invokes no target. Original provenance is not a
reusable principal. Later preparation and first admission have separate evidence;
worker invocation/results, execution recovery and external cancellation remain open.

The later [private preparation unit](QUEUED_INTENT_PREPARATION_2026-10-18.md)
revalidates retained intents against current enrolled authority and the original
deadline within a sealed guard. This unit requires its own exact selected-head
evidence; queued-acceptance CI does not verify later preparation changes. Current
qualification is recorded in the selected head's
[PR #70 checks](https://github.com/shadowhunter-92/agentbridge/pull/70/checks)
and phase receipt. Preparation
adds no public execution path, operation admission/linkage, worker, results,
execution recovery or remote cancellation.

The separate [private first-admission extension](QUEUED_INTENT_PREPARATION_2026-10-18.md)
uses that preparation object with the exact operator-bound gateway. Current
policy, original/current approval requirements, explicit persisted operator
budget policy, quota, target and fixed authorization deadlines are checked under
the shared transaction locks. A successful transaction records one immutable
task/operation/event link, holds the reservation and changes SUBMITTED to WORKING.
WORKING means awaiting dispatch; the operation remains UNKNOWN. Existing claims
in any operation state are rejected. There is no worker, invocation, result,
settlement, automatic reconciliation or remote-cancellation path in this unit.
Its `08355255` selected-head CI and source-associated phase receipts qualify
these changes independently of the preparation head's results. Final-runtime
affected regression recorded 490 passing cases and ten expected SQLite skips
for PostgreSQL-only checks; final budget-policy and process-crash cases recorded
14 passes separately. Earlier overlapping draft receipts retain their own source
associations. Overall P04 remains PARTIALLY TESTED.

The later [audit-capacity unit](AUDIT_CAPACITY_AND_RETENTION_2026.md) adds a
default 100,000 rows / 64 MiB actual UTF-8 JSON / 16 KiB new-entry limit at the
existing SQL boundary. It preserves historical rows and rejects saturation in
the same governance transaction. Startup and offline migration verify initialized
counters against retained data without resetting discrepancies. Store-API prefix
retention refuses holds, retained operations/links, nonterminal tasks and pending
reservations, and keeps the chain head. Privileged raw SQL deletion and old
retention binaries remain outside that API guarantee; production deletion stays
forbidden. Local SQLite/PostgreSQL test receipts are source-associated separately;
consult the selected follow-up head for CI. This is PARTIALLY TESTED retention,
not independently accepted custody or a bound on all database/evidence storage.

The stream unit's recorded final local SQLite/PostgreSQL regression had 228 passed and 2
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
historical cleanup separately. Maintained and historical branch heads retain
their separate dispositions. Later units require exact selected-head checks and
source-associated receipts; descriptions here do not extend earlier test scope.

Current branch count is six after the approved October22 consolidation. Earlier inventories above and dated branch reports retain their historical counts.
