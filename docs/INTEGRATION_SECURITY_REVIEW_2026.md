# Security-boundary integration audit — 13 October 2026

**Review class:** source inspection + exact-commit CI observation; **not** a penetration test, independent attestation, production certification, or comprehensive security approval.

## Boundaries reviewed

| Boundary | Observed implementation | Unresolved failure mode / required acceptance |
| --- | --- | --- |
| Action authorization | Policy, request-auth, budget, operation state and approval modules + negative CI checks | Verify user/agent identity provenance, target binding, multi-tenant principal isolation and complete dispatch-path enforcement across all adapters |
| Destination fencing | `FencedPostgresDestination` checks a monotonic lease inside the same PostgreSQL transaction as effect insertion; `FencedSqliteTarget` uses a single-writer transactional gate | Does not protect uninstrumented SaaS API writes, partitioned writable primaries, or arbitrary external tools; require destination-owner integration and adversarial testing |
| Duplicate/lost ACK recovery | Durable operation identifier and duplicate denial; single-authority fault drills in CI | Unknown outcomes must **not** be converted to success/failure without authoritative independent observation; no universal exactly-once guarantee |
| Receipt verification | Ed25519 destination receipt bound to agent ID, operation ID, fingerprint, outcome, external reference | Signature authenticates the signer's *claim*, not physical completion; key enrollment/custody and target-side measurement still need qualification |
| Independent readback | PostgreSQL SELECT-only adapter, HTTPS pinned-origin adapter and separately signed attestations | No independently operated production observer, hardware-backed signing custody, tested rotation, real customer-source access or complete revocation evidence |
| Witness/audit | Checkpoint/witness signing and offline hash verification | Authenticity/anti-rollback requires current independently retrieved witness; operator custody and retention not certified |
| Egress | Docker-only network confinement, allowlisting and TLS identity primitives; Kubernetes policy specimen | Not deployed on real enforcing CNI. IPv6/metadata/DNS bypass, workload identity and third-party destinations still require operator acceptance |
| Protocol fidelity | Basic pinned MCP/A2A wire forms and unsupported-operation rejection | Not full reference transport/session/streaming/cancellation compliance; downgrade semantic risks remain |
| Release supply chain | Locked selected runtime dependencies and CI-only ephemeral signatures | Trusted signing issuer, published provenance, reproducible toolchain/extras, upgrade and rollback operational evidence unqualified |

## Regression evidence

Integration branch merge preserves R4 and main histories. On commit
`6fab0dd798e2e625d8aa33af4f718a75ba0b7455`,
GitHub Actions run #366 reported 11/11 successful jobs including Python
3.11 and 3.12, PostgreSQL recovery, egress isolation, package checks and
the 90-second SQL soak. The earlier failing run identified a SQLite-reserved
`sqlite_` table name; fixed in the above commit without removing tests.

**Interpretation:** No unexplained failures remain **within tested CI
coverage** at that exact commit. This is not proof of exhaustive authorization
paths or the operational gates listed above.

## Merge/release decision

- Integration PR #41: draft engineering alpha review.
- No unrestricted consequential-action production release.
- No designation of compliance certification, court-admissible proof,
  independent witness custody, full MCP/A2A conformance or global
  exactly-once effects.
- External evaluator acceptance and production-system trust qualification
  are separate gates.

Next security review: threat-model all entry/dispatch paths and prove
untrusted caller cannot substitute destination/observer keys or change
the authorized fingerprint; include hostile SDK inputs and third-party
adapter negative tests. Do not generalize the controlled SQLite/PostgreSQL
results to targets without their own enforceable fencing.
