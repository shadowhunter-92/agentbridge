# Participating-worker lifecycle preparation — October 30, 2026

**IMPLEMENTED / UNTESTED. Production remains BLOCKED.** This private candidate extends the existing disposable PostgreSQL drill. No new test, repository import, PostgreSQL connection, OS worker, Docker action, cloud call or fault drill has been executed for this unit. Static syntax and byte-association receipts are preparation evidence, not runtime qualification.

The exact baseline is `ec1754bc57db4a7835163c82796b83a6cc6d6200`, tree `6be4bbf8d0027a7965fe65a3f4525aabb50f25ab`. The baseline source archive contains 456 tracked files. The new unit has no commit, hosted CI run, publication or merge. External evidence manifests pin the final candidate bytes and preserve the earlier partial inventory. The separate PR76/PR77 composition is not changed or relabeled as this candidate's baseline.

## Existing authority and new behavior

`tools/drill_pg_stale_leader.py` retains its original `_delayed_worker` and `run_disposable_drill` functions and default scenario. An explicit `AGENTBRIDGE_STALE_LEADER_SCENARIO=worker-lifecycle` selects the new scenario; `AGENTBRIDGE_DISPOSABLE_STALE_LEADER=1` is still required by the CLI. No product `src/` module, licensing, CODEOWNERS or workflow is changed.

The new scenario:

1. Rejects production, nonnumeric-loopback routes, a database other than exact `agentbridge_test`, missing explicit port/user/password and timing outside the declared bounds. It reconstructs the DSN with explicit local routing, public search path and existing SQL limits. A local name and credentials alone are not authorization: a separate runner must establish that the actual disposable fixture is owner-controlled before execution.
2. Initializes the existing fence/effect schema once before participants. UUID-owned scope, agent and two distinct operation IDs avoid resetting existing retained state. This does not qualify concurrent cold initialization or migrations under traffic.
3. Spawns an old participating worker that acquires one epoch, acknowledges two renewals and deliberately drains renewal. Only known `FenceDenied` acquisition refusals may retry; uncertain acquire/renew responses stop dispatch. Invalid or changed renewal epochs also stop it.
4. Uses another bounded connection to observe that exact old owner/epoch expire on the database clock. A late observation cannot start a replacement after the parent observation window. It then starts one replacement participant, requiring a strictly higher epoch.
5. Allows the replacement one destination call, with an injected lost acknowledgment. It never repeats an uncertain effect, reacquires after that effect, generates a replacement operation ID to evade duplication, resets an attempt or releases a reservation. The resumed old worker performs separately named stale-renewal and stale-effect negative probes, which must both refuse precisely.
6. Reads exact persisted agent/operation/fingerprint state over another connection and invokes the existing receipt verifier using this trial's preselected public key. Missing, mismatched, unavailable or untrusted readback retains effect observation `UNKNOWN`. A signed receipt authenticates the signer's statement; it is not proof of an external physical or financial effect.
7. Records owned-child exits, bounded join/terminate/kill attempts and queue/barrier cleanup errors. Messages claiming success cannot override abnormal exits, forced cleanup, unknown liveness or missing observations. The CLI exclusively reserves a new result path before starting this scenario; an existing path refuses before another trial runs.

This is drain-and-expire worker handover on **one authoritative PostgreSQL writer**, not immediate lease release, an HA service, consensus, physical standby promotion, independently administered readback or a real network partition. No physical promotion command exists in the scenario.

## Bounds and honest measurements

Defaults are TTL **3s**, renewal interval **0.25s**, parent observation window **30s**, exactly two participants and one replacement effect attempt. Allowed TTL is **0.75–5s**, renewal interval **0.05s–TTL/3**, and observation window **4×TTL–45s**. Each participant has at most 64 known-refusal acquisition attempts; the parent accepts at most 128 worker messages of at most 4,096 JSON characters and at most 128 expiry observations.

The reconstructed connection carries 5s connection establishment, 5s server lock and 10s server statement settings. These settings do **not** prove a hard client receive deadline under a real network blackhole. The parent checks its window around observations and avoids starting later actions after expiry. Owned-child cleanup permits up to 2s initial join, 3s after termination and 2s after kill per child. Initialization/SQL and cleanup are not claimed to fit inside the 30s observation window. A separate supervising process with a hard wall-clock cap remains required for any actual drill.

Parent monotonic receipt timestamps include scheduling, queue and observation latency. Server time is separately recorded. `drain_to_higher_epoch_seconds` and `drain_to_observed_replacement_effect_seconds` are observed worker-handover components, not database RTO, a promise of recovery within one TTL, production SLOs or cross-host clock differences. The report retains actual trial identifiers and sampled server observations. It does not delete fence/effect history.

`source_commit` and `source_manifest_sha256` deliberately remain null inside an unbound tool result; a supervising source-pinned runner must associate them externally. `governed_unknown_count`, `governed_reservations`, `workload_rpo` and `physical_database_failover_rto` remain null because this raw destination drill does not exercise those systems. `separate_connection_observed_effect_count` describes a self-operated separate connection only. A zero stale count is reported only after exact signed readback of this trial's one expected effect; no missing readback is translated to zero.

## Prepared negative harness

`tests/test_pg_worker_lifecycle_harness.py` uses scripted lease/destination responses, fake clocks, fake barriers/queues/process handles and fake parent observations. Its autouse fixture guards `psycopg.connect`, `multiprocessing.get_context`, `socket.create_connection` and `subprocess.Popen`. It is not a general sandbox for arbitrary imported code. Tests that need the parent context replace it with an explicit fake; fake time is local to the drill module and does not replace Python's shared time module.

The prepared assertions cover known refusal versus uncertain response, no resend or operation-ID regeneration, invalid epochs, renewal refusal, drain and queue deadlines, stale-gate specificity, abnormal exits/cleanup errors, malformed/oversize/nonfinite messages, missing or contradictory effect readback, untrusted receipt classification, strict local configuration, late initialization/expiry observation and compatibility of default CLI selection. These are unexecuted source assertions. Fakes cannot establish actual SQL concurrency, receipt cryptographic correctness, worker isolation or real timing. Existing receipt and PostgreSQL integration tests remain required regressions.

## Requirement and progress register

| Inventory item | Status for this unit | Prepared coverage / remaining evidence |
| --- | --- | --- |
| WL-01 competing acquire / exact one owner | PARTIALLY TESTED | Existing eight-contender PostgreSQL test remains unchanged and separate. This scenario is sequential drain/expiry handover; no new contention result exists. |
| WL-02 renew and bounded participation | IMPLEMENTED / UNTESTED | Source plus fake lease/deadline negatives prepared. Needs bounded offline test execution and actual two-worker trial. |
| WL-03 old process pause/kill/handover | IMPLEMENTED / UNTESTED | Cooperative drain, resume and stale probes implemented. Forced process kill and network partition remain NOT STARTED for this unit. |
| WL-04 / WL-05 uncertain acquire or renew | IMPLEMENTED / UNTESTED | Fake response-loss assertions; actual connection/response-loss injection remains NOT STARTED. |
| WL-06 expiry while waiting | PARTIALLY TESTED | Existing fresh-clock lock/expiry regressions preserved. New driver refuses late expiry response before starting replacement; not executed. |
| WL-07 lost effect ACK / no replay | IMPLEMENTED / UNTESTED | One replacement attempt, exact signed readback and no resend. Needs actual source-pinned result and independent QA. |
| WL-08 concurrent same-ID / changed-fingerprint collision | NOT STARTED | Fake duplicate-return classification does not implement or qualify a new simultaneous collision trial. Retain existing duplicate-gate integration regressions. |
| WL-09 unavailable, contradictory or untrusted readback | IMPLEMENTED / UNTESTED | Fake parent negatives retain UNKNOWN; actual readback fault injection remains NOT STARTED. |
| WL-10 parent/queue/child failure and cleanup | IMPLEMENTED / UNTESTED | Pure harness assertions prepared; actual process cleanup/abrupt failure remains NOT STARTED. |
| WL-11 wrong target / bootstrap | IMPLEMENTED / UNTESTED | Strict local configuration and one parent initialization only. Actual fixture identity must be granted; concurrent cold bootstrap not claimed. |
| WL-12 governed immutable attempt / budget reservation recovery | NOT APPLICABLE | No governed route or accounting change. Existing dispatch/tenant recovery regressions remain required and separate; integration with this PostgreSQL destination remains NOT STARTED. |
| WL-13 independently fenced physical promotion/rejoin | BLOCKED | No promotion capability added. Requires authoritative old-primary fencing outside divergent writable copies, scoped topology and actual partition/rejoin evidence. |
| CI and publication | NOT STARTED | No new commit or hosted run. Publication requires applicable owner approval after local review and test results. |
| Production / external acceptance | BLOCKED | A self-operated disposable trial cannot grant independent security, destination-operator or production acceptance. |

The next authorized internal action is independent source review followed by a bounded offline harness run from this exact private source. Fix and preserve any failures before actual PostgreSQL trial preparation. A later execution grant must pin the disposable container/database identity, route, source manifest, existing initialization scope, outer timeout and retained result path. No historical cloud grant or expired cleanup deadline is reused.
