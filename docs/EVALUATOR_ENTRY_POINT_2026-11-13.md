# Governed evaluator entry point — November 13, 2026

**PARTIALLY TESTED; production NO-GO.** Executable baseline:
`f309a35cb5c3ec4164acea5ba2622dc04be6807c`, tree
`17fd9e48708ebed43971a4d0b53b9e6cf703c609`. This documentation-only unit is
a later addition; the baseline CI does not qualify these new documents.

## Audited and already implemented

The maintained source already has the official MCP 1.30.0 stdio demonstration,
human approval, a shared durable governance store, bounded one-shot dispatch,
local fenced destination, separate read-only observation and offline evidence
verification. PR #88 at `6cbc8da9407c6d977bab2da8b85fe30a351c61ca` passed all
24 checks before owner-approved merge. Its [core run](https://github.com/shadowhunter-92/agentbridge/actions/runs/43367985086)
is distinct from [main's own 16-job run](https://github.com/shadowhunter-92/agentbridge/actions/runs/43371818001).

The root README did not expose that runnable route. Existing evaluation and
pilot material lives in `docs/`; some entry points name older release branches
or historical unsigned wheels. Those historical artifacts must keep their
original identity.

## Change

The README now leads with the governed MCP example, three terminal commands,
its pinned executable source, an explicit limitations block and links to an
[external validator kit](../evaluation/external_validator_kit/README.md).
The full protocol/architecture/four-offering material remains below. The
November 3 checkpoint is retained and explicitly historical.

The clone remains the documentation checkout; a detached `.evaluator-runtime`
worktree selects the executable pin without removing the newer kit files.
The validator kit includes native and Compose setup, positive/negative checks,
timing fields, feedback, trust boundaries and a review scope. The
[design-partner kit](../evaluation/design_partner_kit/README.md) includes a
discovery script, scoped consent draft and results register. All legal terms
are templates requiring qualified legal review; no legal compliance or
executed agreement is claimed. Runtime, dependency locks, Apache-2.0, NOTICE
and CODEOWNERS are unchanged.

## Validation and remaining evidence

The existing documentation checker passes with zero local file-target issues.
Whitespace and changed-file scope are checked separately. This low-impact
documentation unit adds no runtime behavior; prior native/container results
are not reclassified as new independent evaluations.

The under-ten-minute setup objective remains **BLOCKED** on actual unrelated
evaluator timing; internal warm execution is insufficient. The source-pinned
baseline container's optional MCP closure remains unqualified until a
separately tested exact fix is selected. Container negative cases are a
separate unit. No LangChain wrapper is claimed here.

No issue edit, outreach, registration, cloud resource, paid action, release,
branch deletion or new protected-main merge is part of this unit. Issue
#33/#36/#44/#38 updates remain to be prepared and owner-reviewed using the
eventually published documentation revision. The five legacy commit behaviors
and Issue #38 require their own remaining semantic/owner acceptance.

## Next acceptance and rollback

Internal reviewer checks instructions, source pin, retained limitations and
all local links. After permitted publication, record this unit's exact commit
and hosted CI separately. Protected-main merge still needs explicit approval.
An ordinary revert of this documentation unit restores the previous entry
point; no data, operation history or branch ref is deleted.

External acceptance remains three unrelated developer reports, five real
consented buyer interviews, an independent security review, a separately
administered destination/readback and a written supervised evaluation. A sent
invitation, indicative quote or successful internal run does not satisfy any
of those gates. P35 and AWS remain untouched/on hold.
