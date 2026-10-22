# Approved branch consolidation — October 22, 2026

Status: VERIFIED IN CI for the named merged source; overall engineering alpha
PARTIALLY TESTED and unrestricted consequential-action production NO-GO.

The owner approved PR70 readiness and a normal merge of reviewed head
`7415718eef8b9650875885ab17eb4d15acf3489b`. Resulting main
`b0afb7f1da1634330747389e19c896fd7002bd83` preserves prior main73aafd60 and that
reviewed head as its two parents, with identical tree
`b123faa45279b0306296ecb3f2c9c9949ad37269`. Its [main CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/39736688053)
passed16/16 jobs. Reviewed source7415718 separately passed24 jobs across seven
workflows, including [source CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/39706489270).
These are separate exact-head executions. GitHub auto-marked PRs56–69 merged.

Before cleanup all20 live heads were preserved in a Git bundle, restored into
a fresh bare repository and checked with fsck. Bundle SHA-256:
`fe4f2debe997b4ed047748edec46605ceda0f3c3112f3d80b537282e1df54038`.
For each of14 approved redundant dependency refs, fresh checks confirmed the
expected SHA, unprotected status, merged PR, no open dependent PR and reachability
from merged main. One atomic deletion used exact expected-SHA leases; no
history was rewritten. Local branches, dirty checkouts and older backups remain.

Six remote refs remain: `main`, `feat/durable-tenant-task-intents-2026-10-17`,
`integration/r4-main-reconciliation-2026-10`, `prod/readiness-pass`,
`release/r4-internal-gates-2026-10` and
`release/rc0-hardening-and-validation-2026-10`.
The feature ref is retained for active development; maintained historical
integration/release/readiness refs preserve their separate evidence.
Earlier20/25/28-head reports and draft-PR statements are historical observations.
Further merge/deletion decisions need their own review and owner authorization.
No release, paid infrastructure, production deployment or external acceptance
was established by consolidation.
