# Trust → Evidence integrated evaluator sprint — October 2026

**Current stage:** synthetic developer alpha. The end-to-end code is new in PR #42; no independent evaluation or production acceptance inferred.

## Reproduce
From a fresh Python 3.11/3.12 environment:
```bash
python -m pip install -e ".[test]"
python -m examples.trust_evidence_end_to_end
python -m pytest tests/test_trust_evidence_end_to_end.py tests/test_evidence_sdk_adversarial_contract.py tests/test_observer_rotation_transitions.py -q
python -m tools.benchmark_trust_evidence --count 12
```
All commands are synthetic. No AWS resources, banking access, money movement, private customer credentials or production calls.

## End-to-end test contract

1. Generate separate ephemeral caller, destination, readback and audit signing keys. All trust roots are pinned for the local test but administered by the same process.
2. Bind the target, capability and action payload to a deterministic operation fingerprint. Deny an unsigned/unapproved or mismatched request.
3. Consume a one-time fingerprint-scoped human-approval record and persist a durable UNKNOWN operation claim before dispatch.
4. Execute via the SQLite destination's atomic fencing check and intentionally drop its acknowledgment **after committing**.
5. Verify the destination refuses duplicate execution and the ledger refuses replay while UNKNOWN.
6. Read the actual sandbox destination state through a separate read-only database connection, verify the destination Ed25519 signature and create a separately signed readback attestation.
7. Verify both signatures against explicitly pinned keys/registered observer key, reconcile UNKNOWN → succeeded, append audit history and validate a separately signed audit checkpoint.
8. Reject denied approval and no-readback cases without creating a misleading success/failed result.

## Known limitations

The workflow is a **single-process, two-database local simulation**, not an independently administered observer. Its receipt is a signed statement of a controlled SQLite effect, not a proof of settlement at a third-party API. The synthetic reviewer does not satisfy production cryptographic reviewer authorization. No payment/order/customer integration; no real Kubernetes workload identity or independent witness retention. The benchmark measures loopback synthetic latency and deliberately makes **no p99 production SLO claim**.

## Four-product impact

| Product | Completed in this sprint | Next external acceptance |
|---|---|---|
| OSS | One reproducible wheel-installable Trust/Evidence flow | Three independent clean installs; official MCP/A2A subset matrix |
| Trust | Request-bound signed identity, one-shot approval, durable unknown, fenced local destination and replay denial | Independently controlled third-party adapter and adversarial authorization tests |
| Evidence | Signed receipt, source readback, registry pinning, reconciliation and signed audit checkpoint | Separate administrator and original target custody, tamper-proof witness storage |
| Enterprise | Operational release/safety requirements documented, CI and AWS reference drills already present | Supported SSO/tenancy, automated HA, audited signing/release, on-call and paid deployment |

## External feedback and buyer discovery

- Developer criterion: 3 consented evaluators submit immutable SHA, exact command output, negative-test result, setup time, interoperability observations and actionable defects. Invitations are **not** successful evaluations.
- Buyer criterion: interview 5 qualified financial-operations, platform security and compliance budget owners about a real failure/unknown-outcome scenario, existing tooling, costs and procurement. Do not count hypothetical enthusiasm as willingness to pay.
- Pilot: obtain one written, bounded, synthetic/read-only evaluation scope with decision-maker and success criteria. Never route consequential orders or payments through the alpha.
- Commercial/legal: preserve currently granted Apache 2.0 rights; do not alter licensing, claim regulatory certification or publish proprietary modules without counsel and explicit owner approval.

## Remaining P0/P1/P2 gates

P0: separately administered key lifecycle and authoritative observation; destination-side enforcement at actual external systems; workload-authenticated egress and IPv6/DNS bypass acceptance.
P1: automatic split-brain-safe HA with repeated RPO/RTO and chaos runs; independently published signed immutable releases; live rolling app+database migration rollback.
P2: full claimed-version MCP/A2A reference transport/lifecycle conformance; full-path production CPU/RSS, fault injections, backpressure and overload measurements with customer-agreed budgets.

**Go/no-go:** BUILD developer evaluation; production NO-GO.
