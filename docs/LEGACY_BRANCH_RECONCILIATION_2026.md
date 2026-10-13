# Legacy `prod/readiness-pass` reconciliation ledger — 13 October 2026

The five unique commits were traced from the branch tip back to common ancestor
`f108dce057a157fb61c6f635dfef4939fdc34fe4`. **No commits have
been deleted or force-rebased.** The integration branch is not a
cherry-pick of the legacy branch; it retains a more recent R4 architecture.

| Legacy SHA | Primary content | Reconciliation decision | Remaining verification |
| --- | --- | --- | --- |
| `1efbac5` | Structured telemetry, OIDC JWKS, store-backed approvals, audit retention/legal hold, config validation, graceful shutdown | **Retain as historical reference**; overlapping concepts exist in R4, but semantic parity is NOT fully proven | Compare behavior under failure and ensure old and new storage layouts are not misidentified as compatible |
| `d4a2a4b` | Fixes JWKS parsing, retry scope, metric-label cardinality, shutdown duration, truncation verification and tests | **Retain as security/correctness checklist** pending exact source-level parity evidence; do not bulk-merge stale handlers | Targeted negative tests for every fix |
| `4db3cc1` | README / API / deployment operational documentation | **Superseded in public presentation by main PR #39**, retain source as reference for any missing accurate endpoint descriptions | Link check and endpoint-by-endpoint documentation review |
| `9006a0b` | Concurrency barrier timeout and shared overall deadline | **Retain test-harness history**; current R4 concurrency tests provide newer coverage | Confirm stress assertions are never silently skipped |
| `779e81e` | Four SQLite writers and a best-effort barrier replacing harder stress conditions | **Do not automatically incorporate**: it weakens a stress scenario to reduce flakiness | Preserve stronger contention tests; fix actual storage races instead |

## Criteria before deleting the old branch

- Keep all five Git SHAs permanently discoverable via issue #38 and this ledger.
- Validate actual behavior of legacy observability, JWKS, retention and
  graceful-shutdown edge cases against integration implementation, not just
  overlapping filenames or API names.
- Retain the old branch until a maintainer signs off those tests and the
  latest CI remains green. No branch deletion is performed here.

**Result:** all five unique commits are *accounted for and explicitly
retained or superseded*, but their functional parity is not fully verified.
Issue #38 must remain open until that independent cross-check is completed.
