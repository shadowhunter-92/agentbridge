# Active leader stop and committed lease-reply loss — November 5, 2026

**PARTIALLY TESTED. Engineering alpha; production remains BLOCKED.**
Historical November 5 preparation is retained below. On November 12, root's
fresh reviewed attempt 2 accepted all three actual bounded local faults.
See `HA_CRITICAL_PATH_2026-11-12.md` for the current results, source/receipt
binding, stopped-fixture first attempt and remaining acceptance boundaries.
The two separate governed PG crash cases remain IMPLEMENTED / UNTESTED:
their owner-approved native operator later refused its read-only PUBLIC TEMP
prerequisite, before any role/schema writes or governed crash trial.

1. **Baseline / ending:** local branch `fix/ha-forced-stop-2026-11-04` starts at
   `35f37222597341d2c23e9cd9d0baddf1e36f99f7`. Changes remain uncommitted.
2. **Audited:** the existing participating-worker drill, offline harness,
   PostgreSQL fencing methods and retained v5 process-containment evidence.
   The three earlier cooperative trials are preserved and are not rerun here.
3. **Existing controls:** database-clock leases, post-lock epoch validation,
   exact operation identities, signed destination records, separate readback,
   bounded SQL settings and UNKNOWN/no-replay behavior.
4. **Changes:** three explicit scenarios extend the existing drill.
   `worker-forced-stop` observes at least two renewals and an active-ready
   event, then stops only its owned old process while that loop continues
   renewing. It waits for authoritative expiry before a higher-epoch
   successor, probes the stale token under distinct probe identities and
   observes one signed destination effect. Old and replacement result
   queues are separate: abrupt termination cannot poison the successor's
   channel. The default cooperative scenario is preserved.
5. **Tests:** 206 offline cases passed: 123 existing cooperative cases and
   83 fault cases. No failures, errors, warnings or unexpected capability
   attempts; source pins matched before/after. This covers exact owned stop,
   active renewal, unknown replies, no retry/dispatch, typed observations,
   stale refusal, watchdog/deadline and cleanup failures, production
   refusal and exclusive CLI receipts. The first 187-case invocation passed
   assertions but its outer gate refused pytest's hostname metadata call;
   that attempt is retained. The corrected runner uses a synthetic hostname
   and explicit timeout/asyncio plugins. These are mocked control-flow tests,
   not executed OS stops or PostgreSQL fault qualification.
6. **CI:** no new hosted run or commit exists for this local unit. Historical
   CI and controlled staging results do not qualify the new source.
7. **New defects / limitations:** no product runtime file changed.
   The two reply-loss cases intentionally execute a successful lease method
   before withholding its return from the worker. They exercise the
   application boundary after method completion; they do not drop a real
   network packet or establish a client-network timeout bound.
8. **Internal partials:** root-reviewed actual forced-stop, acquire-reply-loss
   and renew-reply-loss trials; source/result association; later real TCP
   reply loss, physical election/promotion/partition, governed task/accounting
   recovery, active migrations and sustained full-route performance.
9. **External / permissions:** actual local trials require the precise
   reviewed runner and one-shot local grant. No AWS, outside contact,
   deployment, release or publication is included. Independent custody,
   security review, evaluators and buyer/pilot acceptance remain external.
10. **Branch / PR:** isolated local worktree only. No commit, push, main merge
    or branch deletion. Apache-2.0, CODEOWNERS and all product runtime files
    remain unchanged.
11. **Security / release gates:** production NO-GO. An uncertain lease reply
    stops the worker with zero destination attempts; the parent requires
    exactly one injected marker, the stopped UNKNOWN verdict, a recorded
    lease and zero observed effects. It never settles a business outcome,
    refunds exposure, regenerates an operation ID or resends an effect.
    P35 remains BLOCKED and untouched.
12. **Next:** root reviews the frozen source, fault-specific containment
    runner and exclusive output scope; executes each actual scenario once;
    preserves failures and exact authoritative readback. Only matching
    actual evidence can advance these scenarios beyond PARTIALLY TESTED.

## Controlled acceptance and remaining boundaries

A stopped old process cannot resume. The parent stale-token calls are explicit
gate probes, using an operation identity distinct from the successor effect;
they are not retries of that effect. Forced-stop intervals are named separately
from cooperative drain intervals and physical failover RTO remains null.

`lease-acquire-reply-loss` and `lease-renew-reply-loss` preserve the worker's
UNKNOWN classification. One bounded observer connection may confirm a
recorded lease and zero effects, but that sample is not independent custody or
permission to retry. Exactly one actor is expected in these scenarios.

Actual execution must keep the existing cap of three application processes,
at most one exactly pinned and witnessed OS console helper, live PID/parent/
image/Job verification, bounded startup gates and empty native PID-list
cleanup. Forced termination cannot require a finally receipt from the
terminated worker; its native ownership/liveness evidence must supply that
association. It must not weaken normal-exit checks for other actors.

Use only the existing explicitly disposable PostgreSQL lab, revalidating its
exact container ID, image, loopback binding and fresh mapped port before
reading the local test configuration in memory. Do not reuse historical port
values or reset tables, rows, leases or database state. Each trial receives
fresh UUID scope/agent/probe/effect identifiers and retains its rows.

The outer process supervisor must bind the exact frozen source and retain an
exclusive fresh attempt directory before any effect. It must start the direct
pinned base interpreter with the virtualenv context, enforce finite per-trial
and overall budgets, and close only its owned process Job on failure.
No universal exactly-once, arbitrary-hostile-code isolation, physical HA,
production SLO or external acceptance is claimed.

