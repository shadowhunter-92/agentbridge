# Branch reconciliation, historical CI, and merge gates

**Updated: October 11, 2026. Status: engineering review, NOT production-ready.**

## What was reconciled

- Primary consolidated draft review: [PR #32](https://github.com/shadowhunter-92/agentbridge/pull/32), branch `release/rc0-hardening-and-validation-2026-10`.
- Historical production readiness PR #17 was closed **unmerged** after transplanting selected useful production-readiness modules and correcting unsafe parts. It diverged from the current main and is not a safe direct merge. Its branch is retained for historical recovery.
- Duplicate engineering PRs #27–#31 were closed unmerged after verifying their exact branch heads are ancestors of the cumulative release review branch.
- No old engineering branch was deleted. Branch heads are retained for safety and review provenance; GitHub's available connector does not expose branch deletion.
- Main has not been changed by these actions. **Closing a duplicate PR is not equivalent to code deployment or a production release.**

## CI audit: failure history is preserved

Historical failed runs include:
- 38128768386 (both Python matrix jobs failed on an earlier integration)
- 38128922383 (Python 3.11 failed, Python 3.12 passed; SQLite WAL initialization contention)
- 38131485656 (Python 3.11/3.12 failed; initial R3 synthetic drill expectations)
- 38131554980 (Python 3.11/3.12 failed; earlier budget exposure view test)

Later corrected runs with three successful jobs:
- 38131638734
- 38132332997
- 38133074316
- 38133546126

The jobs are Python 3.11, Python 3.12, and real PostgreSQL integration. CI failures are not erased or rewritten; assess only the latest immutable tested commit SHA. Later run results are available on PR #32.

Additional release-review fixes since those runs:
- Production mode is normalized for `prod` and `production` across target ACLs, operator cost schedules and SQL-backed nonce replay.
- Production direct gateway requires a unique, signed operation identity and includes the operation ID in the request-specific approval fingerprint.
- PostgreSQL integration now includes unknown-operation reconciliation and reservation settlement across independent connections.
- Optional OpenTelemetry tracing dependencies are declared in pyproject.
- README, API, enterprise, deployment and roadmap pages explicitly state supported status and unresolved issues.

## Merge gates

A green CI run verifies the configured tests; it does NOT establish target execution truth or production safety. **Do not merge PR #32 into main as a production-ready change until:**

1. Critical authorization and egress/SSRF paths are independently audited, and hostile inputs fail closed.
2. Operator reconciliation is tied to authenticated, independently verified external-state evidence. Simple digest submission by a reviewer is not proof of an action.
3. Signed durable checkpoints, off-process anchors, and durable legal holds make audit retention demonstrably safe across replicas.
4. Real multi-process kill/restart, lost-ack, network partition, Postgres failover and restore exercises pass with retained evidence.
5. Current supported MCP/A2A behavior is tested against reference clients with precise unsupported-feature inventory.
6. Dependency scanning, container hardening, reproducible packaging, performance SLOs and independent security signoff are recorded.
7. A qualified operator explicitly approves the supported narrow scope and abort/rollback plan.

R4–R7 market and infrastructure milestones additionally require external integrations, feedback, adoption, paid pilots and operational capacity. They cannot be made complete by source code alone.

**Current recommendation:** keep PR #32 as a draft and do not delete the preserved history until the release process has concluded.
