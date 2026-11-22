# Governed MCP container qualification — November 15, 2026

**PARTIALLY TESTED. The enumerated local container cohort passed; production remains NO-GO.**

Work started November 13, implementation/tests and image build ran November 14,
and the final fresh container trial ended November 15 at
`2026-11-15T01:46:35.438245437Z`. This is a bounded synthetic local evaluation,
not a security certification, production SLO, trusted release or external acceptance.

## Exact source and environment

- Baseline: `f309a35cb5c3ec4164acea5ba2622dc04be6807c`.
- Implementation: `3654826a01aa227018ac25face04819d52926ac4`;
  implementation tree: `3c8041818e559c75396abf9ab77045ca26438d7b`.
- Exact tested image: `sha256:3b29af0162c97c1affc80121251367d64535a065b0044f34103d6cfb83babbe2`,
  local tag `agentbridge-governed-mcp-demo:qualification-20261114-r5`.
- Base: `python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322`.
- Actual container Python 3.12.13, Linux x86_64/musl on Docker Desktop 29.7.2,
  WSL2 kernel 6.18.58.1. Each workload remained capped at one CPU and 512 MiB;
  these are local runtime settings, not a performance acceptance claim.
- All 107 copied Python/lock payload hashes matched the local tested files,
  including core Python source, both example modules, inspector and both locks.
  `src/`, original demo modules, Apache-2.0, NOTICE and CODEOWNERS were unchanged.

The documentation-only follow-up commit is recorded in the coordinating phase
report. It does not change the qualified image payload. There is no hosted CI
run for this new local branch yet; historical main or PR #88 CI does not qualify it.

## What was already implemented

The existing demo already used official MCP 1.30.0 stdio, shared SQL governance,
signed request/operation identity, request-bound one-shot approval, reservation,
a fenced synthetic SQLite effect and signed readback through the existing verifier.
Its native fault assertions, eight-second MCP request deadline, explicit
half-second timeout case, 60-second approval input limit and 100-second CLI
watchdog remain unchanged. The same-operation test probes admission again and
requires refusal before dispatch; the gateway never automatically replays an
uncertain effect.

## New bounded implementation

`tools/qualify_governed_mcp_container.py` runs six actual local CLI scenarios
against an exact local image ID. It supplies scripted approval/denial stdin,
creates a fresh retained evidence volume and inspects each actual container.
It requires nonroot UID/GID 10001, network-none, read-only root, dropped
capabilities, no-new-privileges, CPU/memory/PID limits and no bind mounts.
The producer must have exited with zero status, no live PID and no OOM, with
no running user of its evidence volume, before readback starts.

A separate container mounts the evidence volume read-only and runs
`tools/inspect_governed_mcp_evidence.py`. It checks signed request binding,
exact approval action/cost, ledger and reservation linkage, durable budget
exposure, destination effect count/receipt, audit bytes/chain and the original
freshness-bound evidence verifier. It does not settle, refund, reconcile or replay.

SQLite WAL may need writable SHM metadata even with a read-only SQL connection.
The inspector copies the stopped producer's DB/WAL/SHM family into private
temporary storage, verifies copied bytes against source SHA256, opens the copy
with `mode=ro`, explicitly closes handles and verifies all original source
hashes remain unchanged. Each file is capped at 16 MiB and the evidence directory/
database family at 32 MiB; container temporary storage remains 64 MiB.
It never uses `immutable=1`, ignores WAL, checkpoints or modifies original evidence.
This is a stopped local-producer inspection, not live backup or distributed
snapshot qualification.

## Actual final container trial

Accepted run: `9b1a3be8913b4153897575990844a053`.
Retained volume:
`agentbridge-governed-evidence-9b1a3be8913b4153897575990844a053`.
Window: `2026-11-15T01:44:35.282561845Z` through
`2026-11-15T01:46:35.438245437Z`.

| Scenario | Effects | Durable operation | Spent cents | Reserved cents | Required behavior |
| --- | ---: | --- | ---: | ---: | --- |
| Success and duplicate replay | 1 | succeeded | 1000000 | 0 | Fresh signed readback verifies; repeated operation refused before a second dispatch |
| Lost ACK | 1 | unknown | 0 | 1000000 | Exact committed-ACK-drop fault; fresh signed effect/readback exported; no automatic reconciliation or resend |
| Denied approval | 0 | no operation | 0 | 0 | Denied scoped approval; no dispatch, operation claim or exposure |
| Tool error | 0 | unknown | 0 | 1000000 | Exact synthetic pre-effect MCP isError; no success accounting or refund |
| Timeout | 0 | unknown | 0 | 1000000 | Exact official SDK 408/0.5-second deadline; controlled target exits without effect; UNKNOWN retained |
| Concurrent local claim | 1 | succeeded | 1000000 | 0 | Two admissions share one local gateway/store; exactly one admission/effect, one refusal and no duplicate replay |

All six passed their separate read-only checks. This is not two independent
leaders, physical split-brain, an external financial service or independently
administered custody. The amount is the synthetic USD10,000 action label.

## Hash closure and actual negative verification

The Dockerfile installs `requirements-runtime.lock` and the demo's
`requirements-mcp.lock` in **one** `--require-hashes --only-binary=:all:` invocation,
then runs `pip check`. Actual installed metadata exactly matched 19 runtime
pins plus 14 nonoverlapping MCP supplemental pins: 33 packages, plus the pinned
base image's pip 25.0.1. Every MCP transitive dependency is covered by that
combined graph on the reviewed Linux/Python 3.12/x86_64 Alpine platform.

The supplemental file is generated from the actual pinned-base pip wheel
resolution, constrained by existing runtime versions, using
`tools/lock_governed_mcp_demo.py`. Resolution used a version-only constraints
view because hashes would activate pip hash enforcement before the new MCP
graph had been resolved. Final installation always requires all hashes.
The renderer rejects wrong platform/SDK, non-PyPI/non-wheel source, duplicate
packages, malformed hashes and conflicting runtime pins. Core security-update
pins retain their single owner in the runtime lock.

An actual network-disabled negative container presented the official MCP 1.30.0
wheel against an intentionally wrong required SHA256. Pip refused with
`THESE PACKAGES DO NOT MATCH THE HASHES` and exit 1. The downloaded wheel's
SHA256 was `666edb5009503e1047c9d60346a756f94b261f05cc2625f23d41c728ffc484d0`.
This proves that exercised hash-refusal boundary; it does not establish
SBOM completeness, artifact signing, SLSA level, institutional identity,
published-artifact installation or absence of dependency vulnerabilities.

Changes to runtime pins require combined-image revalidation. In particular,
this record binds the original baseline graph; a separate Pydantic security
update is not automatically qualified by these old-source results.

## Tests and failures retained

One exact final native test invocation ran the original 14 demo cases and 42 new
qualification cases: **56 passed, zero failures/errors/skips, 46.776 seconds**.
The new cases cover durable accounting/approval/effect/audit disagreement,
forged receipt/request binding, uncheckpointed WAL, source/copy bytes,
aggregate limits, producer liveness/OOM, weaker container controls and lock
renderer refusals. Test approvals are scripted callbacks, not independently
verified human identities. Do not add overlapping earlier cohorts to this total.

Earlier evidence remains preserved:

- The initial pip resolution refused missing MCP hashes when a hashed constraints
  file activated strict mode; the reviewed version-only resolution then succeeded.
- The first real read-only-volume inspector refused SQLite WAL auxiliary access.
  Private DB/WAL/SHM copying fixed that boundary without granting original writes.
- The first Windows private-copy draft left SQLite handles open; its native cohort
  had 13 failures and 21 passes. Explicit handle closure fixed the cause; no test was
  skipped or weakened.
- Earlier r3/r4 container cohorts each passed six cases on their own image/source;
  they are historical corroboration, not extra final test cases.
- The first fresh November 15 r5 cohort failed during MCP initialization under
  the unchanged eight-second budget with SDK `BrokenResourceError` after cold
  startup. It exited 1 and remained unaccepted.
  Read-only inspection found zero operations, effects, dispatches, spend and
  reservations, and no MCP handshake. The failed volume
  `agentbridge-governed-evidence-6b45c9acb0684c73a5fd055f0d516ea0` is retained.
  A fresh unchanged-image, unchanged-timeout trial passed above. **Cold-start
  reliability under these limits remains unqualified.** No deadline was increased
  and no previous operation or uncertain effect was resumed.

The local evidence packet retains JUnit, full build logs/image facts, both
successful and failed trial directories, Docker inspection, original volume
bytes, per-scenario source hashes, immediate verifier results and hash-refusal
logs. Evidence names include `AgentBridge-governed-container-final-tests-20261114-r5.xml`,
`AgentBridge-governed-container-trials-20261115-r5-retry1` and
`governed-container-hash-negative-20261114`. They are local qualification
artifacts; no original evidence volume/container was deleted.

## Reproduce and remaining acceptance

Use the [demo quickstart](../demo/governed-mcp-demo/README.md) to build and run.
The qualification runner itself requires only host Python's standard library
and Docker; the image contains the pinned protocol/evidence dependencies.
The normal demo still uses interactive `compose run`, not `up`.
The verifier's 300-second freshness rule remains intact; saved verification
records what was accepted at observation time and does not refresh old attestations.

Separate local keys, containers, connections and caller-retained expected action
do not establish independent organizations or trustworthy real-world fulfillment.
The existing verifier's expected-action flag means it compared the supplied
retained file; independent custody remains false.

Still open: hosted exact-head CI, integrated-image revalidation after dependency
updates, cold-start repeatability, other architectures/Python versions,
independent security/evaluator/pilot acceptance, external destination enforcement,
workload mTLS/CNI, physical HA, broader protocol conformance, release trust and
production performance qualification. No LLM/LangChain, Stripe-native fencing,
real money movement, production deployment, cloud use, P35 work, branch deletion,
protected-main merge or release publication was added or claimed.
