# Branch lifecycle and review ownership (October 2026)

This file records a **non-destructive** reconciliation. Branches are not releases,
and deleting old branches without verifying ancestry and unique changes is unsafe.

## Canonical active lines

| Branch | Purpose | Rule |
| --- | --- | --- |
| `main` | Public, experimental default-branch prototype | Accept scoped, reviewed PRs only |
| `release/r4-internal-gates-2026-10` | Cumulative security/recovery implementation (draft PR #34) | No unconditional production merge |
| `docs/public-refresh-rebased-2026-10` | Public README and contributor experience (PR #39) | Review and merge independently of PR #34 |

## Incorporated history

On October 12, the GitHub compare operation against the R4 branch returned
`status=ahead, behind=0` for these predecessor branches, meaning their branch
HEAD commits are ancestors of R4:

| Incorporated branch | R4 ahead | R4 behind |
| --- | ---: | ---: |
| `release/rc0-hardening-and-validation-2026-10` | 221 | 0 |
| `engineering/production-hardening-2026-10` | 285 | 0 |
| `engineering/r1-r2-trust-execution-2026-10` | 266 | 0 |
| `engineering/r3-reconciliation-audit-2026-10` | 255 | 0 |
| `engineering/r3-staging-faults-2026-10` | 258 | 0 |

PR #32, which targeted the already-incorporated RC0 branch, was **closed
unmerged** on October 12. Its work is preserved as ancestry of PR #34.
Closing the PR does not publish the code on main.

## Divergent branch: do not delete

`prod/readiness-pass` is **not** a clean ancestor: R4 compared ahead 331,
behind 5. Those five distinct historical commits must be examined for any
still-relevant changes, security implications and provenance before deciding to
archive/delete. Do not force-merge or blindly cherry-pick this branch.

## Dependency branches

Dependabot branches and their PRs are independent change proposals. Review
version constraints, lockfile diffs, vulnerability reports and CI before
merging/closing; do not silently remove them for cosmetic cleanliness.

## Safe cleanup sequence

1. Review the current main, PR #39 and PR #34 CI by exact commit SHA.
2. Merge only PR #39 after validating the current README, links, quickstart, and CI checks. Historical PR #35 was closed unmerged after its branch conflicted with the separately merged WAL contention fix.
3. Keep PR #34 draft until the release-gate register and independent reviewers
   approve the applicable operational scope.
4. Before deleting any obsolete branch, check no other open PR points to it,
   validate ancestor status at the **current** R4 HEAD, retain a tag or commit
   reference for recovery, and apply repository retention policy.
5. Never delete a branch with unique commits until the changes are explicitly
   audited and reconciled.
6. Do not conflate a code merge with production deployment authorization.

## Community-facing success criteria

Prioritize reproduced installations, independent integration feedback, fixes,
real-world use, responsiveness and maintainability. Neither GitHub stars nor
the number of branches establishes trust or commercial demand.
