# AgentBridge scoped developer-alpha release candidate

**Release class:** `alpha` review packet; not published, tagged,
certified or approved for consequential production use.

## Proposed allowed scope

- Python 3.11/3.12 local installation in disposable environments.
- Six registered protocol families for the **documented basic tool-call
  subset** only, not full asynchronous A2A/MCP transport conformance.
- Standalone offline Trust/Evidence SDK, synthetic signed receipts and
  independently keyed sandbox readback, single-authority SQLite/PostgreSQL
  recovery tests.
- Synthetic/read-only developer evaluations, with no external private data,
  payment authorization, production credentials or consequential writes.

## Candidate acceptance inputs

| Evidence | Requirement | Status |
| --- | --- | --- |
| Two-parent branch history | current main + cumulative R4 preserved | Integrated in PR #41 |
| Full CI | eleven jobs pass on exact SHA | Passed on `6fab0dd` (run #366); reverify after release-doc changes |
| Python installer | clean editable/wheel environment at 3.11 and 3.12 | CI internal install done; external clean-room report missing |
| SBOM, locked runtime and container | publish immutable hashes and verify reproducibility | Internal review only; no public signed release manifest accepted |
| Signed release identity | separately held key, verifiable provenance and approved publisher | **NOT QUALIFIED** |
| Rollback | restore previous build with immutable digest, migrate synthetic DB, verify audit continuity | Procedure defined below, end-to-end executed rollback evidence **PENDING** |
| Independent security / destination operator | review of applicable P0/P1 gates | **NOT QUALIFIED** |
| Three independent integrations | consented evaluations with reproduction logs | **PENDING** |

## Draft release procedure (non-production only)

1. Freeze the candidate SHA and collect CI job URLs/artifact digests.
2. Install wheels in clean 3.11/3.12 virtual environments using pinned
   dependencies. Record wheel SHA256 and compare it with the build output.
3. Run `python -m examples.verify_synthetic_action_evidence`,
   negative evidence-verification tests, protocol subset smoke tests and
   SQLite/PostgreSQL recovery fixtures. No customer data.
4. On staging with a disposable database, capture export, hold records,
   operation keys, signed audit checkpoint and witness state. Rehearse
   upgrade and rollback using immutable tested artifact digests.
5. After rollback, verify prior data, schema compatibility, no duplicate
   operations, chain continuity and receipt verification. If any discrepancy:
   STOP and retain a NO-GO report; never discard unknown outcomes.
6. Prepare release notes that explicitly list unsupported transports,
   session semantics, witness/custody and production infrastructure gaps.
7. Submit evidence to independent reviewers before converting PR #41 from
   draft. No public registry publishing or customer pilot until approved.

## Product positioning guardrail

Describe AgentBridge as an **experimental agent-action interoperability,
authorization and evidence SDK**. Do not assert it is the "TCP/IP of agents",
a compliance-certified gateway, court-grade proof of execution, or a
recognized standard. Compliance support is an unvalidated customer
hypothesis and requires legal/organizational controls beyond logs.

**Decision:** developer alpha INVESTIGATE/BUILD; unrestricted production
NO-GO. Publishing credentials and legal review are outside the current CI
evidence boundary.
