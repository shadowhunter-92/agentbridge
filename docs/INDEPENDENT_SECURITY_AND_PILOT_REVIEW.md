# AgentBridge independent security and pilot review package

**Status:** request for external assessment only. This document is not an
independent review, certification or proof of enterprise readiness.

## System-under-test

Use the fixed SHA of PR #34 reviewed by the evaluator; do not evaluate a
moving branch. Shared libraries are `src/governance`; interoperability
adapters live in `src/protocols`; the bounded reference egress proxy is
`src/proxy`. The proposed products are OSS, Trust, Evidence and (future)
Enterprise built on one kernel.

## Security evaluation matrix

| Focus | Expected adversarial attempt | Fail-closed acceptance |
|---|---|---|
| Identity | Forged, revoked, stale or cross-tenant signer | No authorization or settlement |
| Approvals | Change request arguments after approval or replay a prior approval | No action or budget settlement |
| Destination effects | Lose ACK after commit, retry same operation from two workers | Unknown is preserved; destination effect not dispatched again |
| Readback | Tamper destination row, invent source result, compromise readback key | Reconciliation refused; outcome remains unknown |
| Operator settlement | Swap reviewer, operation ID, outcome or signed evidence digest | Exact operation-bound signature required |
| Audit | Delete/fork/restore old ledger; replay old witness checkpoint | Against independently retrieved latest witness, rollback rejected |
| Egress | Direct worker TCP, metadata endpoints, DNS rebinding, IPv6, CONNECT/SNI mismatch, ECH | No unauthorized or ambiguous destination |
| Protocol | MCP unsupported method, A2A incompatible lifecycle/error/cancellation | Unsupported semantics rejected, not silently translated |
| Database | Old leader writes after promotion, network partition, PITR restore and migration | External target rejects stale fencing epoch; no duplicate effects |
| Package | Alter wheel or manifest, vulnerable dependency or base OS | Detached signature and hashes fail; CI blocks unreviewed image |
| Scale | Overload, crash, DB saturation, long-lived unknown operations | Defined p95/p99/error/RSS thresholds and safe shedding |

## Required independent inputs

- Reviewer identity and explicit engagement scope, authorized test systems,
  allowed dates, disclosure channel and responsible bug handling.
- Separate read-only target credentials, a verifier key administered outside
  AgentBridge write authority, independently retrieved checkpoint witnesses.
- Evidence of deployed firewall/CNI enforcing the policy, not merely YAML.
- Operator-approved fault and recovery logs, RPO/RTO measured under controlled
  failures, target audit corroboration.
- Artifact source commit, tool version, vulnerable dependency inventory and
  complete container SBOM.

## Pilot candidate acceptance protocol

1. Get written authorization from target owner to run a bounded read-only or
   synthetic agent action. Specify systems, data retention, work hours and
   emergency disable procedure.
2. Install fixed-source wheel; run sandbox replay and observer checks locally.
3. Establish read-only authoritative state API and two independently controlled
   Ed25519 keys; verify exact action ID, fingerprint and evidence origin.
4. Enable human approval and audit retention; do not run autonomous write
   workflows until separately approved in staging.
5. Reproduce lost-acknowledgment and recovery with verifiable single target
   effect, preserved budget hold and signed reviewer settlement.
6. Collect independent install duration, failed integrations, risk reduction,
   operator burden and written user/buyer feedback; never infer willingness to
   pay from technical interest alone.

## Acceptance signatures and results

Record reviewer, affiliation, credentials, commit SHA, environment, scope,
start/finish times, reproducible checks, failures, mitigations, residual
risk, supporting artifact digests and approval decision. Do not claim
external acceptance without an independently completed record.

## Known boundaries to disclose unprompted

The reference CONNECT proxy is not certified as production workload-authenticated
network egress. The PostgreSQL fencing row must be enforced by the destination;
a replicated DB alone cannot stop an old primary on a different side of a
partition. Signed claims do not prove real-world completion without trusted
readback semantics and key custody. Protocol tests cover a declared subset.
Local CI performance smoke is not a production SLO. A paid Enterprise package
remains unvalidated.
