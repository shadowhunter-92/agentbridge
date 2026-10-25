# Engineering blockers and unresolved acceptance - October 24, 2026

Last reviewed October 25, 2026. **PARTIALLY TESTED; production NO-GO.** This register distinguishes internal work, owner decisions and independent acceptance. Needed AWS trials have a separate USD 100 owner authorization; releases, main merges, access grants and correspondence retain their gates.

## B01 - Literal all-four-historical-heads-green statement

Status: **BLOCKED**. Historical 7a10a5f CI failed and cannot honestly be rewritten as success. Corrected 143c93d passed 24/24 and was owner-merged; main 635288a passed16/16.

Responsible: Maintainer / engineering. Next action: Record acceptance against corrected current source while preserving the original failed run; do not rerun to erase it.

## B02 - Live third-party sandbox/custody qualification

Status: **BLOCKED**. Free environment setup was authorized. The owner subsequently created a separate AgentBridge Stripe account; guided setup opened its dedicated test sandbox dashboard. No live activation, secret-key access, API credential provisioning or provider API trial was performed by the assistant. The earlier disabled controls belonged to an unrelated account. Salesforce still returned a generic provisioning error after its verification challenge; no specific rejection cause is established. Native service idempotency is not proof of atomic monotonic fencing, and a separately administered destination/readback operator remains unavailable. Mocks or a usable sandbox dashboard cannot establish live destination fencing.

Responsible: Maintainer, internal engineering and a consenting destination operator. Next action: Resolve environment provisioning through normal vendor controls; the owner must complete any financial-account activation/identity submission. Establish an actual atomic target-side contract before implementing or qualifying consequential native service execution. Preserve the current production refusal and UNKNOWN/no-resend semantics. See [the capability and acceptance matrix](EXTERNAL_DESTINATION_FENCING_2026.md). Access expansion, live trials and independent custody retain their applicable authorization gates.

## B03 - Independent legal/security/buyer/developer/pilot acceptance

Status: **BLOCKED**. Engineering cannot self-issue legal compliance, independent review, returned evaluations, buyer demand or written pilot acceptance.

Responsible: Qualified external reviewers and consenting evaluators. Next action: Prepare internally reviewable material; keep actual outreach/access/spending within existing authorization and record returned evidence separately.

## B04 - Protocol labels and SLSA trust requirements

Status: **NOT STARTED**. MCP SDK major versions are not assumed to be wire-protocol revisions; a generated provenance statement is not assumed to confer SLSA Level 3.

Responsible: Internal engineering. Next action: Verify official version/platform requirements before implementation or support claims.

Additional internal work remains in the [complete phase checklist](ENGINEERING_PHASE_PROGRESS_2026-10-24.md): historical-key recovery, exact offline upgrade qualification, reference-indexed retention, operated identity/network/HA, reproducible releases and sustained full-route performance. A local signing follow-up or staged manifest is not production acceptance. The isolated replay-capacity item remains BLOCKED and untouched.
