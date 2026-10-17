# Branch documentation dispositions — October 16, 2026

## October 17 recorded remote inventory

The maintainer's read-only October 17 snapshot records **19 remote heads** and
**14 open draft, unmerged PRs (#56–#69)**. It supersedes cached branch totals
for current status, while the original cached comparison below remains
historical. These head SHAs came from the supplied inventory; the local
comparison checks their Git objects, ancestry and documentation paths against
`46777f8c953690fca81c6d11e7b70372b8dd5c77`. No fresh online query,
behavioral branch audit, merge approval or deletion approval is claimed here.

| Recorded remote branch | Exact head | Documentation paths differing | Documentation disposition |
| --- | --- | ---: | --- |
| `feat/shared-tenant-task-streams-2026-10-16` | `46777f8c953690fca81c6d11e7b70372b8dd5c77` | 0 | Draft PR #69 cumulative source; current comparison baseline |
| `feat/durable-task-event-bytes-2026-10-16` | `07303af24857322c59c02977dbcca67d74e91d8f` | 1 | Draft PR #68 source ancestor; retain phase evidence pending review |
| `feat/durable-task-history-cap-2026-10-16` | `4892b37a72a6a11a346fe5b3347d708bf26e226e` | 2 | Draft PR #67 source ancestor; retain phase evidence pending review |
| `fix/tenant-policy-publication-2026-10-16` | `573826fcb29039e9438ea5a8746a21faf9f7b409` | 3 | Draft PR #66 source ancestor; retain phase evidence pending review |
| `fix/sqlite-mutation-boundaries-2026-10-16` | `8ab8ff3c16d3859a6ff86ea4e66154332fa2d1e4` | 4 | Draft PR #65 source ancestor; retain phase evidence pending review |
| `fix/task-atomic-tenant-scope-2026-10-16` | `eb2dcea8d722def931b95f15a8767d2592c54ad6` | 6 | Draft PR #64 source ancestor; retain phase evidence pending review |
| `fix/tenant-signing-trust-coordination-2026-10-16` | `d0881b937d2568e4e01fb02044bf466aea609e9a` | 7 | Draft PR #63 source ancestor; retain phase evidence pending review |
| `fix/tenant-postgres-namespace-aliases-2026-10-16` | `228398ca9a0d95d49b4fbea9d0468998e1a10ff7` | 8 | Draft PR #62 source ancestor; retain phase evidence pending review |
| `feat/durable-tenant-quotas-2026-10-15` | `7ee8252c814c4f9e4f20440951eac4a00938757d` | 9 | Draft PR #61 source ancestor; retain phase evidence pending review |
| `feat/atomic-governance-admission-2026-10-14` | `23b3d00413f4331ea949edc70560d2d9962eefe7` | 11 | Draft PR #60 source ancestor; retain phase evidence pending review |
| `feat/atomic-governance-settlement-2026-10-14` | `f2629d2baf23ff83cbbe7c43dc7257c63639cc93` | 12 | Draft PR #59 source ancestor; retain phase evidence pending review |
| `feat/tenant-migration-2026-10-14` | `51e3f4c6f9c85371ec0a2339b312f78823b26a40` | 13 | Draft PR #58 source ancestor; retain phase evidence pending review |
| `feat/tenant-isolation-runtime-2026-10-14` | `10393374e1cb05778b70eb5ddde65d343ff79a50` | 14 | Draft PR #57 source ancestor; retain phase evidence pending review |
| `feat/tenant-authority-foundation-2026-10-14` | `423a6893e6c77a8212f8a1fe37d5e91c8745db04` | 14 | Draft PR #56 source ancestor; retain phase evidence pending review |
| `integration/r4-main-reconciliation-2026-10` | `06538c52d7b6f797a0dccbaef0c519da5d819618` | 39 | Preserved historical line; inspect unique behavior before any cleanup |
| `main` | `73aafd60a0eec121a10245a307a4a8ee268f7ed5` | 15 | Separate main baseline; tenant draft not merged |
| `prod/readiness-pass` | `779e81ed6571384783310cb9e5d9bb7b71412639` | 77 | Preserved historical line; inspect unique behavior before any cleanup |
| `release/r4-internal-gates-2026-10` | `f1c75d0687aa8d1e690539ec858aef171d26df01` | 62 | Preserved historical line; inspect unique behavior before any cleanup |
| `release/rc0-hardening-and-validation-2026-10` | `da4e6b4280602e2d20d3b7f092c8dbae908f132e` | 75 | Preserved historical line; inspect unique behavior before any cleanup |

Current counts cover `docs`, `README.md`, `CHANGELOG.md`, `RELEASING.md`,
`SECURITY.md` and `CONTRIBUTING.md` at the frozen source heads, before this
documentation correction. They count paths, not defects. The #56–#69 heads
are ancestors of the cumulative source; ancestry does not establish acceptance
of every requirement. Current unit contracts belong on the reviewed cumulative
line, with historical evidence kept at its original SHA. No old branch is
rewritten, bulk-merged or deleted by this proposal.

PR #69's tenant-native stream allocation limits are in the source baseline.
They observe existing durable tasks; executable asynchronous intent, worker
recovery and external cancellation remain outside that source contract.

## October 16 cached comparison (historical)

The October 16 section is a **cached local comparison**, not a fresh online branch inventory.
The comparison used the authoritative checkout's Git refs without changing its
branch or unfinished stream work. Coverage: 23 local heads, 18 cached origin
heads and one symbolic origin/HEAD alias, spanning 25 unique commits. A separately
retained 17-head live snapshot predates PR #68; it is not the current total.
See [current source and draft dependencies](CURRENT_ALPHA_STATUS.md).

| Cached origin line | Head | Documentation files differing from `07303af` | Disposition |
| --- | --- | ---: | --- |
| `main` | `73aafd60` | 14 | Main baseline; tenant draft docs are not yet integrated |
| `feat/tenant-authority-foundation-2026-10-14` | `423a6893` | 13 | PR #56 dependency; retain phase evidence |
| `feat/tenant-isolation-runtime-2026-10-14` | `10393374` | 13 | PR #57 dependency; later bounded phase addenda supersede future statements |
| `feat/tenant-migration-2026-10-14` | `51e3f4c6` | 12 | PR #58 dependency; offline scope remains |
| `feat/atomic-governance-settlement-2026-10-14` | `f2629d2b` | 11 | PR #59 dependency; later atomic admission supersedes the old admission gap |
| `feat/atomic-governance-admission-2026-10-14` | `23b3d004` | 10 | PR #60 dependency |
| `feat/durable-tenant-quotas-2026-10-15` | `7ee8252c` | 8 | PR #61 dependency; admission caps are distinct from storage/network limits |
| `fix/tenant-postgres-namespace-aliases-2026-10-16` | `228398ca` | 7 | PR #62 dependency |
| `fix/tenant-signing-trust-coordination-2026-10-16` | `d0881b93` | 6 | PR #63 dependency and deliberately older evaluator pin |
| `fix/task-atomic-tenant-scope-2026-10-16` | `eb2dcea8` | 5 | PR #64 dependency; task status remains non-executable |
| `fix/sqlite-mutation-boundaries-2026-10-16` | `8ab8ff3c` | 3 | PR #65 dependency |
| `fix/tenant-policy-publication-2026-10-16` | `573826fc` | 2 | PR #66 dependency |
| `feat/durable-task-history-cap-2026-10-16` | `4892b37a` | 1 | PR #67 dependency; event bytes are a separate later unit |
| `feat/durable-task-event-bytes-2026-10-16` | `07303af2` | 0 | PR #68 cumulative source used for this documentation correction |
| `integration/r4-main-reconciliation-2026-10` | `06538c52` | 37 | Earlier preserved integration; do not replay its superseded docs over current source |
| `prod/readiness-pass` | `779e81ed` | 75 | Historical evidence; name is not production approval |
| `release/r4-internal-gates-2026-10` | `f1c75d06` | 60 | Protected historical evidence, not a separate supported release |
| `release/rc0-hardening-and-validation-2026-10` | `da4e6b42` | 73 | Protected historical evidence, not a separate supported release |

Counts cover `docs`, `README.md`, `CHANGELOG.md`, `RELEASING.md` and `SECURITY.md`
at the frozen heads, before this correction. They measure changed documentation
paths, not behavior or correctness. Full tenant-stack SHAs are in current status.

Local-only unique heads `cc705be`, `6771be7`, `4604adc`, `fe69425`, `89b1cc3`,
`37274bc` and `27321de` were also compared. These are audit/continuation, backup,
status-stream, reconciliation and production-restriction checkpoints. Their
original source and evidence remain historical. Local shared-stream branch
`feat/shared-tenant-task-streams-2026-10-16` points at `07303af`; uncommitted
changes are outside the compared source and do not qualify fleet limits.

## October 16 corrections and preservation (historical)

Main and every tenant-stack head inherit the same old handoff/index and branch
audit pages. The index omitted 13 later unit documents. The handoff's `b94e2cf`
baseline, pending target-restriction CI and 30-head inventory are historical.
October 11–14 reports also contain pending PR #41, no-deletion and original-heads-
online statements that applied to their phases. Their tables/results remain
unchanged; notices direct readers to current status.

A later owner-approved cleanup receipt records 20 deletions and five retained
heads, with a restored bundle fsck PASS and all former remote commits recovered.
The retained bundle SHA-256 is
`bed749ea145519a61077c81383409b838aba19b2e264913fbca7a2e7376f469b`.
This records a completed historical cleanup; it is not approval for further
deletion. Remote branch names, local refs and retained commit ancestry must be
reported separately.

That original correction was one local docs-only branch from `07303af`. No old branch was
rewritten or merged, and no online write was performed. Integrate the correction
on the selected cumulative source after review, then refresh the live inventory
and exact integration-head CI. Preserve older immutable reports as historical
evidence instead of copying current claims onto untested older source.

Reproduce the cached comparison with:

```powershell
git for-each-ref --format='%(refname:short)|%(objectname)' refs/heads refs/remotes
git diff --name-only 07303af <exact-head> -- docs README.md CHANGELOG.md RELEASING.md SECURITY.md
git show '<exact-head>:docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md'
```
