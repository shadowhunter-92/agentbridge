# Branch qualification and consolidation — October 13, 2026

Read-only remote inventory froze 26 actual branch heads. The symbolic `origin/HEAD`
alias is excluded from this count. Every frozen head was extracted and tested on
Windows Python 3.12 and Linux Python 3.11 with a separate disposable PostgreSQL 16
database, and each wheel was built and imported outside its source checkout.

The branch matrix uses the same current audit dependency sets, recorded separately
for each platform. It tests compatibility now, not reproduction of historical CI
dependencies or every possible SDK release. Older branches contain fewer tests;
their passing suites do not qualify newer features absent from those branches.
Wheel imports use shared runtime dependencies; the final candidate additionally
receives a fresh hash-locked installation. No historical branch head was rewritten.

## Results

| Branch | SHA | Windows 3.12 | Linux 3.11 | Wheel import | Unique commits vs integration |
| --- | --- | --- | --- | --- | ---: |
| `audit/repo-consistency-outreach-2026-10` | `01a7d8a52f` | FAIL | pass | pass | 13 |
| `dependabot/github_actions/github-actions-696b649f44` | `4aea2a80b5` | FAIL | FAIL | FAIL | 1 |
| `dependabot/pip/fastapi-gte-0.141.1` | `37a1a12c82` | FAIL | pass | FAIL | 1 |
| `dependabot/pip/google-genai-gte-2.16.0` | `619d384444` | FAIL | pass | FAIL | 1 |
| `dependabot/pip/openai-gte-2.51.0` | `47d23c6a02` | FAIL | pass | FAIL | 1 |
| `dependabot/pip/pytest-cov-gte-7.1.0` | `33056f0753` | FAIL | pass | FAIL | 1 |
| `dependabot/pip/pytest-timeout-gte-2.4.0` | `3560f51dcc` | FAIL | pass | FAIL | 1 |
| `docs/public-facing-refresh-2026-10` | `3bec61ae20` | pass | pass | FAIL | 6 |
| `docs/public-refresh-rebased-2026-10` | `34150a901b` | pass | pass | FAIL | 6 |
| `engineering/production-hardening-2026-10` | `a74f515ab7` | pass | pass | FAIL | 0 |
| `engineering/r1-r2-trust-execution-2026-10` | `ef02aeff60` | pass | pass | FAIL | 0 |
| `engineering/r3-reconciliation-audit-2026-10` | `fab51e83f3` | pass | pass | FAIL | 0 |
| `engineering/r3-staging-faults-2026-10` | `8d3230e4f8` | pass | pass | FAIL | 0 |
| `feat/evidence-remote-verifier-oct2026` | `06be04ac22` | FAIL | pass | pass | 19 |
| `feat/explicit-agent-task-lifecycle-2026-10` | `adcf2a2ea4` | FAIL | pass | pass | 9 |
| `fix/sqlite-wal-startup-contention-2026-10` | `5cc7606032` | pass | pass | FAIL | 1 |
| `hardening/protocol-failclosed-competitive-research-2026-10` | `8fa5c47a6a` | FAIL | pass | pass | 5 |
| `integration/r4-main-reconciliation-2026-10` | `cc705be8ff` | FAIL | pass | pass | 0 |
| `main` | `5af3903f0d` | pass | pass | FAIL | 0 |
| `prod/readiness-pass` | `779e81ed65` | FAIL | pass | FAIL | 5 |
| `reconcile/main-into-r4-oct2026` | `0eb2887a96` | FAIL | pass | pass | 0 |
| `release/r4-internal-gates-2026-10` | `f1c75d0687` | FAIL | FAIL | pass | 0 |
| `release/rc0-hardening-and-validation-2026-10` | `da4e6b4280` | pass | pass | FAIL | 0 |
| `security/ip-product-gates-2026-10` | `347ac442a2` | FAIL | pass | pass | 15 |
| `security/main-review-ownership-windows-fix-2026-10` | `da3be09367` | pass | pass | FAIL | 2 |
| `security/repository-ruleset-bootstrap-oct2026` | `b3443d7a20` | FAIL | pass | pass | 16 |

Linux suite passes: 24/26.
Windows suite passes as-is: 10/26.
Standalone source-complete wheel imports: 9/26.
Five historical heads have case-colliding PR templates; current integration fixes
the collision. Exact test logs, JUnit cases, failure traces, wheel digests and CSV
are retained privately under the local audit work directory.

Windows failures include old SQLite startup contention and a POSIX-permission
test incorrectly treated as portable. Linux reproduced contention on the old
Actions-update head and invalid SQLite table naming on the old R4 release head.
Seventeen older wheels omit the `src` namespace required by their console entry
point, despite source-checkout tests passing. The consolidated candidate retains
the newer fixes and adds truthful platform skips and stronger worker assertions.

## Merge and branch reduction decision

Current integration `cc705be8fff535883eee2876c88b0cca4e54da61` includes main
`5af3903f0d17f8b19a66d42c7eedd93489f67a56` by ancestry and is 393 commits ahead.
Draft PR #41 has no main-history conflict at the audited head. Its latest main CI
run #477 passed all 13 jobs and six companion workflows passed. Local changes
still require published exact-head CI and owner review before an online merge.

Do not merge all 26 heads. Seven engineering/release/reconciliation heads are
ancestors. Squash-merged feature heads appear divergent even though PRs #42, #43,
#46, #47, #48, #49 and #50 are merged into their stated targets. The old public
docs and WAL-fix branches are superseded by later main/integration changes.
Ruleset bootstrap source was carried forward into integration. Preserve the
five unique prod/readiness-pass commits through the [parity ledger](LEGACY_BRANCH_RECONCILIATION_2026.md).

Equivalent Python dependency lower bounds are reconciled in requirements.txt
and pyproject.toml; the Actions update is prepared consistently and pinned to
resolved source commits. Do not merge ancient dependency branches containing
old application code; close them as superseded only after the consolidated
published checks pass.

Recommended maintained lines: **main + integration + temporary legacy review**.
That permits a target of **3 active branches**, or **5 total** while retaining two
protected release-history heads. Reaching 3 total requires separately approved
archival tags/bundles and deletion of protected historical release branches.
No branch, tag, PR or setting was changed online in this audit.

## Prepared online sequence — requires owner approval

1. Preserve all 26 SHAs in recoverable history and publish the consolidated local
   changes as a review branch/PR into integration; run full exact-head checks.
2. Review the alpha scope and security changes; merge into integration, then
   review PR #41 into main. A code merge does not approve production use.
3. Close the six superseded dependency proposals after equivalent checks pass.
4. Retain permanent archive references and close or unlink obsolete PRs before
   deleting feature/history heads. Respect deletion protection and audit any
   owner-approved exception. Never force-push or discard unexplained unique work.
5. Re-read live heads before acting; any later remote work must be reconciled.
