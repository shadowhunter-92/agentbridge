# Branch reconciliation — October 14, 2026

> **Historical checkpoint.** This record applies to its stated commits and test
> environment. PRs #51, #52 and #41 subsequently merged; main baseline is
> `483bc98234ced2b876a6b296a1e1fd292747942c`. See the
> [current handoff register](HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md) for ongoing work.

The owner requested comparison and merging without losing work. A verified
pre-consolidation Git bundle and exact ref manifest were saved locally first.
All 27 remote heads in this inventory are retained in the consolidation ancestry;
their original commits, complete file trees and source history remain reachable.
No original branch or tag was deleted or force-pushed.

Seventy-five commits appeared outside current ancestry because of squash merges,
rebased public docs, equivalent dependency updates and the older readiness pass.
All files introduced by those branch lines are present in the current tree.
Prior PR metadata, exact dependency requirements, the byte-identical ruleset
utility and the legacy functional ledger were compared before resolving history.

For the already reviewed squash/superseded lines, conflict resolution explicitly
retains the current implementation. Those merges record original history; they
do not reactivate old handlers, restore retired defaults or weaken concurrency
tests. A clean three-way merge was used when it reproduced the exact current
tree. Every history merge was checked to leave that tree unchanged and make its
original head reachable. This establishes history preservation, not universal
semantic equivalence of every historical behavior.

The sole new runtime correction fixes integer-second SQLite lease truncation.
The destination now retains fractional SQL time, including in existing SQLite
schemas with INTEGER affinity. Tests exercise the boundary and preserve the
stale-leader, lost-ACK and duplicate-effect checks without scheduler sleeps.

| Original branch | Original SHA | Resolution and evidence |
| --- | --- | --- |
| `audit/repo-consistency-outreach-2026-10` | `01a7d8a52f3f2d36f6b44dec8c2572ac79af32bc` | explicit current-tree resolution; original history preserved: Original head of merged PR #49; retain its pre-squash commits while keeping subsequent verified corrections. |
| `dependabot/github_actions/github-actions-696b649f44` | `4aea2a80b574b82949f23616fded48a082c9ed58` | explicit current-tree resolution; original history preserved: setup-python v7 already applied consistently using its verified source commit; retain current Actions pins. |
| `dependabot/pip/fastapi-gte-0.141.1` | `37a1a12c828debee35e8af62bf413ca23d0ef4ff` | clean three-way history merge: Equivalent dependency lower bound already present in requirements.txt and pyproject.toml; keep the reconciled runtime graph. |
| `dependabot/pip/google-genai-gte-2.16.0` | `619d38444484466be8546b6dde2478f50a160414` | explicit current-tree resolution; original history preserved: Equivalent dependency lower bound already present in requirements.txt and pyproject.toml; keep the reconciled runtime graph. |
| `dependabot/pip/openai-gte-2.51.0` | `47d23c6a027a45af18bab18bc9546384f804b42a` | explicit current-tree resolution; original history preserved: Equivalent dependency lower bound already present in requirements.txt and pyproject.toml; keep the reconciled runtime graph. |
| `dependabot/pip/pytest-cov-gte-7.1.0` | `33056f0753ad49730c8d5dc70ef6b926590bcaa8` | explicit current-tree resolution; original history preserved: Equivalent dependency lower bound already present in requirements.txt and pyproject.toml; keep the reconciled runtime graph. |
| `dependabot/pip/pytest-timeout-gte-2.4.0` | `3560f51dcc5f0ba7bee836dc32c81a62bf302ea3` | explicit current-tree resolution; original history preserved: Equivalent dependency lower bound already present in requirements.txt and pyproject.toml; keep the reconciled runtime graph. |
| `docs/public-facing-refresh-2026-10` | `3bec61ae2013baf2b5563f97598d113c0315f17b` | explicit current-tree resolution; original history preserved: Rebased public docs incorporated through PR #39; current README/deployment claims supersede historical text. |
| `docs/public-refresh-rebased-2026-10` | `34150a901b2ee4e640e9294d67476db41a2b7af9` | explicit current-tree resolution; original history preserved: Original head of merged PR #39; retain its pre-squash commits while keeping subsequent verified corrections. |
| `engineering/production-hardening-2026-10` | `a74f515ab744b9b765231a7005dde1722ce6258d` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `engineering/r1-r2-trust-execution-2026-10` | `ef02aeff609df76fa67432157b2d79a70e865a76` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `engineering/r3-reconciliation-audit-2026-10` | `fab51e83f37f5b9e740c0605bc70968e68f5d171` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `engineering/r3-staging-faults-2026-10` | `8d3230e4f8c99b021edd60b9ec13bde10371df2f` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `feat/evidence-remote-verifier-oct2026` | `06be04ac2242b79e2e8d3c21b7c6d942145f38af` | explicit current-tree resolution; original history preserved: Original head of merged PR #43; retain its pre-squash commits while keeping subsequent verified corrections. |
| `feat/explicit-agent-task-lifecycle-2026-10` | `adcf2a2ea4fc1c26a79f03095053ed19d89282f8` | explicit current-tree resolution; original history preserved: Original head of merged PR #50; retain its pre-squash commits while keeping subsequent verified corrections. |
| `fix/consolidated-audit-2026-10-14` | `fe694256ce7b9253af8e1778b6ec7634117803d1` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `fix/sqlite-wal-startup-contention-2026-10` | `5cc7606032c89fbcbe112f1c183083623bdc58e6` | explicit current-tree resolution; original history preserved: Original head of merged PR #37; retain its pre-squash commits while keeping subsequent verified corrections. |
| `hardening/protocol-failclosed-competitive-research-2026-10` | `8fa5c47a6aae3f291fe0fd6198fe8641e648d9f0` | explicit current-tree resolution; original history preserved: Original head of merged PR #48; retain its pre-squash commits while keeping subsequent verified corrections. |
| `integration/r4-main-reconciliation-2026-10` | `55b792a38f2aa3c210f0ecb0ca70b6148cf40cb6` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `main` | `5af3903f0d17f8b19a66d42c7eedd93489f67a56` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `prod/readiness-pass` | `779e81ed6571384783310cb9e5d9bb7b71412639` | explicit current-tree resolution; original history preserved: Five legacy commits compared against current telemetry, JWKS, approvals, retention restrictions, shutdown and stronger eight-writer tests; original code retained in ancestry. |
| `reconcile/main-into-r4-oct2026` | `0eb2887a969bbc3f2e53ed197383508e881a2528` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `release/r4-internal-gates-2026-10` | `f1c75d0687aa8d1e690539ec858aef171d26df01` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `release/rc0-hardening-and-validation-2026-10` | `da4e6b4280602e2d20d3b7f092c8dbae908f132e` | already an ancestor: Already reachable in integration; no additional merge needed. |
| `security/ip-product-gates-2026-10` | `347ac442a227a5796b42fecbf604a3d76b16cfa4` | explicit current-tree resolution; original history preserved: Original head of merged PR #42; retain its pre-squash commits while keeping subsequent verified corrections. |
| `security/main-review-ownership-windows-fix-2026-10` | `da3be09367eaabf759897847025e8f7e96625e8f` | explicit current-tree resolution; original history preserved: Original head of merged PR #46; retain its pre-squash commits while keeping subsequent verified corrections. |
| `security/repository-ruleset-bootstrap-oct2026` | `b3443d7a209d89f8d8527160e571d6e8d568e647` | explicit current-tree resolution; original history preserved: Owner-run ruleset utility carried forward by audit commits 72b5836/f3ed0ea and PR #49; current ownership/protection docs retained. |

Original heads remain online for additional recovery. The maintained-branch
reduction target remains three active lines (or five total with protected release
history), but deleting/renaming those refs is a separate cleanup decision. A
source merge does not itself reduce the number of branch names.

The frozen October 13 26-head test table remains historical evidence. This new
consolidation adds history and the targeted lease fix; exact-head CI and review
are required before it updates integration/main. No original commit was rewritten.
