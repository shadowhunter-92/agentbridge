# Consolidated audit fixes — publication, October 14, 2026

> **Historical checkpoint.** This record applies to its stated commits and test
> environment. PRs #51, #52 and #41 subsequently merged; main baseline is
> `483bc98234ced2b876a6b296a1e1fd292747942c`. See the
> [current handoff register](HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md) for ongoing work.

The owner authorized publishing all verified fixes and documentation corrections.
This review branch is based on integration
`cc705be8fff535883eee2876c88b0cca4e54da61` and targets that integration line.
It preserves current main/integration history. No protected branch is force-pushed,
no historical branch is deleted, and no package, image or production service is
released by this source publication. The initial 26-branch audit and its backups
remain historical evidence for the tested SHAs.

## Included work

- Four security corrections: JWKS retired-key removal, refresh cooldown and
  bounded metadata, bounded HTTP-method metric labels, and mandatory deployment
  administrator secrets. OIDC I/O and shutdown waiting no longer block the loop.
- Cross-worker identity revocation, correct production PostgreSQL observer rows,
  malformed-wire rejection before execution, and removal of legacy translation
  from the executing proxy.
- Signed current-key trust journal with revocation, externally pinned restore
  floors and atomic evidence/budget/audit settlement; adversarial SQL race tests.
- Owner-scoped durable SQL task status/history, compare-and-update, bounded
  admission/events, terminal-state protection and cursor-based pull consumption.
  Remote cancellation, refunds and execution remain distinct operations.
- Installable offline Evidence CLI requiring independently retained expected
  action; packaged MCP demos; explicit SDK extras and startup diagnostics.
- PostgreSQL-enabled hash-locked release-review image, corrected Compose and
  Kubernetes references, dependency update reconciliation, source-pinned Actions,
  Windows CI, local image startup checks and explicit publication gates.
- Canonical documentation catalog, supported scope, corrected claim register,
  all-branch qualification table and a history-preserving consolidation plan.

## Verification and hosted CI

The pre-publication code passed 559 tests plus eight subtests on Linux 3.11 and
556 tests plus eight subtests on Windows 3.12. Three Windows skips cover POSIX
signer permissions and two process-kill checks; Linux ran them. Both platforms
included real PostgreSQL integration. All 26 historical heads were separately
tested on both platforms and their standalone wheels were inspected.

A fresh core wheel installed outside the checkout, passed 12 Trust/Evidence
checks and accepted/rejected offline expected-action inputs correctly. Installed
MCP quickstart and governed demos reached a real local stdio tool. Six local
production-mode image HTTP/process checks and five signing-trust restore checks
passed. Trivy reported no HIGH/CRITICAL OS/Python image vulnerabilities; pip-audit
reported no known advisories in the 22-package locked core/driver graph. Other
SDKs and severity levels are outside those specific scan claims.

The Standard security audit fully reviewed 120/318 frozen pre-fix files and
validated four medium findings. Other artifacts were searched/tested, without
claiming exhaustive static security review of every branch. Fixes have dedicated
regressions; the sealed report and private source handoffs remain local.

Hosted CI must pass on the exact publication head. PR checks cover both main and
integration targets, so the consolidated review receives the companion protocol,
Trust/Evidence, AWS-offline and Kubernetes validation workflows too. Current
check results and exact commit identifiers belong to the linked publication PR.
No prior CI result is relabeled as verification of new source.

## Remaining engineering and acceptance

| Area | Still required |
| --- | --- |
| Protocols | Declared version/transport conformance; actual network task streaming |
| Service isolation | Authenticated tenant boundaries, retention and total quotas |
| Destinations and identity | Non-bypassable external integration and operated workload identity |
| Recovery and releases | Automated split-brain-safe HA, live service migration/rollback, signed public provenance and measured SLOs |
| Independent evidence | Separately administered signer/observer/retention, authoritative external destinations and returned security/developer reports |
| Commercial validation | Actual buyer interviews and supervised design partner; invitations do not establish traction |
| Repository | Review/merge the fixes and PR #41, reconcile six superseded dependency proposals, then approve archival/deletion separately |

The four proposed offerings remain one shared engineering foundation, with
unrestricted consequential-action production **NO-GO**. These unfinished internal
features are not reclassified as external work. See
[current acceptance](CURRENT_STATUS_2026-10-13.md),
[branch decisions](BRANCH_REVIEW_2026-10-13.md) and
[four-product gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md).

## Private data and recovery

Private PDFs/extracts, exposed historical credentials, cloud/mail responses,
populated environment files, keys, databases, virtual environments, test logs
and recovery bundles are excluded. All original local edits and 26 branch heads
were backed up before consolidation. The immutable pre-fix security worktree and
verified source snapshot remain available locally.
