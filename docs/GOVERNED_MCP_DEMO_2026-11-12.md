# Governed MCP local demonstration — November 12, 2026

**PARTIALLY TESTED. Synthetic local evaluation only; production NO-GO.**

Baseline is `35f37222597341d2c23e9cd9d0baddf1e36f99f7`, local branch
`prep/governed-mcp-demo-2026-11-12`. This report records local qualification
before publication. Exact later commit/PR/CI evidence belongs in the coordinating
phase register. Baseline CI does not qualify the new unit.
Exact new-file hashes are retained outside the checkout in the local demo
qualification packet. Core runtime, Apache-2.0 and CODEOWNERS are unchanged.

The [quickstart](../demo/governed-mcp-demo/README.md) invokes a deterministic
client and actual official MCP 1.30.0 stdio server. The existing shared-SQL
`GovernanceGateway`, request-bound approval, budget and `OperationLedger`
control dispatch. The tool reuses `FencedSqliteTarget`, with its own ephemeral
signing key. `SandboxReadOnlyObserver` reads through a separate read-only
connection and signs with a separate in-memory key. Existing `verify_bundle`
must accept before the successful callback returns to gateway settlement.
No duplicate authorization implementation or product protocol change was added.

The synthetic action is 1,000,000 integer cents, USD10,000. Its wire arguments
are bound into the operation fingerprint. It does not create a Stripe object
or move real funds. The local pipe owner is trusted; it can directly operate
the tool or alter its files. The amount is a synthetic action label, not an
independently proven financial settlement. The same operator retains public
roots and the expected action. Separate keys/connections are not independent
custody. LangChain or an LLM is not used or claimed.

## Actual local validation

Final selected suite: **14 passed in 19.76 seconds**, zero failures/errors/skips.
Windows/Python3.12.10, official MCP SDK1.30.0. Native Windows pipe access required
reviewed escalation after the sandbox denied local overlapped pipe creation.
No network endpoint, cloud, credential, customer data or financial effect was
used. The suite's actual approval inputs are test callbacks, not human identity
or independently witnessed approval.

| Actual scenario | Observed controlled behavior |
| --- | --- |
| Success | Approval blocks first; one dispatch/effect; signed readback verifies; 1,000,000 cents spent; no reserved exposure; same-operation replay refused |
| Lost ACK | Exact committed-ACK-drop MCP isError marker; one signed effect; ledger UNKNOWN; 1,000,000 cents reserved; no replay or automatic reconciliation |
| Denied | Denying input; zero dispatch/effect/spend/reservation |
| Tool error | Exact synthetic pre-effect MCP isError marker; zero effects; ledger UNKNOWN and full reservation retained |
| Timeout | Exact official SDK408/0.5-second ClientRequest timeout; controlled target has zero effects; UNKNOWN/full reservation retained |
| Dual claim | Two concurrent admissions within the same gateway/store; one admission/effect and one refusal. No physical split-brain claim |

Additional controls refuse MCP isError/unstructured success, unsupported task
augmentation values, production mode, enrolled multi-tenant legacy access and
existing output reuse. Evidence scenarios reject a different expected operation
and a forged receipt signature through the existing offline verifier. All
actual scenarios check the chained audit. Any unrelated injected-fault error
aborts and records `passed=false`; unknown/zero-effect alone cannot qualify a
negative scenario.

Receipts/JUnit are siblings of this checkout:
`governed-mcp-demo-tests-20261112-attempt3.xml` and the corresponding exclusive
temporary output tree. Earlier attempts are retained: sandbox pipe startup
failure; initial six structured-result failures/eight passes; then the first
14-pass suite before exact fault-marker assertions. A startup failure in the
earliest draft could record an incomplete positive summary; it is unaccepted
because the process exited1 and no handshake occurred. The corrected summary
requires completed workflow and exact expected checks.

## Remaining acceptance

Root separately recorded all six native CLI scenarios with actual stdin input,
matching the frozen source. All six passed in 39.219 seconds overall, and the
success/lost-ACK bundles passed immediate standalone verifier processes. These
inputs were scripted test approvals, not independent human identity evidence.

The root-owned Compose build succeeded from the pinned base image. Its actual
network-disabled, nonroot recipe ran the success flow in 3.577 seconds and its
separate verifier container returned `signature_and_binding_verified`. The
evidence volume is retained. Container negative scenarios remain separately
open; native tests do not qualify those. The five-minute goal excludes installation;
there is no independent setup-time return. Container runtime has no network;
the first build downloads dependencies. Its full MCP transitive closure is not
hash locked, so no reproducible release/provenance claim follows.

The edited video is a visualization of these recorded local results, not live
Stripe footage, a physical transfer or an independently witnessed approval.
Local rendering and review evidence remain separate from product acceptance.

The offline verifier deliberately retains its 300-second readback freshness
rule. Verify promptly after execution. The saved `offline-verification.json`
records actual verification at observation time; it does not extend freshness.
No old attestation is silently refreshed or accepted as current state.

MCP isError, malformed result, protocol/transport failure, failed readback and
deadline raise before success accounting. Ordinary operation replay remains
closed. Broader canonical task/result fixes remain separate local source units
for later reviewed composition; this demo's strict invocation adapter does not
qualify all protocol surfaces or versions.

Independent security/custody, actual Stripe enforcement, external evaluator
returns and pilot acceptance remain open. Physical HA, network partition,
production SLO, universal exactly-once and legal/commercial validation are not
established. No AWS, outbound correspondence, main merge or P35 work is included.
