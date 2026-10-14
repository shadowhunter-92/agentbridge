# AgentBridge commercial strategy decision memo — October 2026

**Classification: strategy hypotheses, not verified customer adoption, legal advice, security certification or valuation forecast.**

## Evidence anchors

- The architecture is one shared governance kernel plus four **possible product packages**, as described in `docs/FOUR_PRODUCT_ARCHITECTURE.md`; not four validated products.
- The AWS two-host exercise demonstrated a PostgreSQL-fenced effect, cross-host lost-ACK and replay denial, stopped-primary promotion, separate-role signed receipt snapshot, and wheel artifact rollback. `docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md` lists important remaining custody, external target, HA and signature limitations.
- CI and repository demos are internal technical evidence. Neither three independent developer reproductions nor paying customers nor a standards-body adoption is verified.

## Positioning

**Suggested initial category:** auditable, recoverable consequential agent action infrastructure. AgentBridge OSS is a narrow protocol/SDK entry path; Trust is decision-time policy; Evidence is outcome reconciliation and integrity validation; Enterprise is potential operator-managed assurance. Focus narrowly on one action type first.

**Do not claim:** bank-grade settlement, universal exactly once, direct proof of real-world fulfillment merely from Ed25519 receipts, SWIFT-equivalent governance, court-admissible proof, SOC 2/HIPAA/EU AI Act compliance, unique market standard or a trillion-dollar TAM.

## Licensing decision gate

Current published source is Apache 2.0. A license change does not revoke prior Apache grants. Copyright ownership and contributor agreements must be audited before any proposed new license. BSL/SSPL are **not OSI-approved open-source licenses**. Do NOT blanket-relicense `src/governance`, `src/api` or `src/evidence` on the basis of a venture narrative. Choose a clear future paid product boundary, verify third-party contributions and inbound rights, seek legal review, then test customer expectations. Alternative: preserve permissive OSS and charge for separately developed hosted enterprise features, support, operating guarantees, compliance workflows or integrations.

## Buyer and reviewer validation (not HFT live trading)

Prioritize **synthetic/read-only** finance/regulated workflow platform engineering, security architecture, internal audit, risk operations and enterprise integration teams. Avoid live orders, transfers and real customer credentials. Recruit 3 independent developer reproducers + 5 buyer interviews before finalizing a paid tier.

Candidate interviews: teams handling approval-bound vendor payments, regulated ticket remediation, financial close approvals, SaaS procurement or compliance evidence collection. Ask for actual incident class, existing controls, annual costs, change-management requirements, buyer/budget owner and time-to-approve a supervised pilot.

### Falsifiable commercial tests

- **SDK demand:** 3 unrelated external engineers install an immutable wheel and reproduce one signed, observer-readback outcome. Pass: at least 2 say they would integrate it in a named workflow and provide reproducible feedback.
- **Pain:** 5 relevant buyers describe specific failures, loss/risk exposure or audit costs without prompting. Pass: at least 3 identify material pain and an existing budget or named budget owner.
- **Pilot willingness:** at least one organization agrees to a written bounded, read-only/synthetic evaluation with acceptance criteria and a named sponsor. A nonbinding discussion is not a paid pilot or PMF.
- **Pricing:** test setup + platform and evidence-event volume separately using real usage assumptions; do not presume USD 50k compliance add-on, insurance discount, or USD 0.001/event demand.
- **Production:** independent destination/operator sign-off, workload CNI, separate signing-key custody, attack tests and external counsel/compliance review as appropriate before live consequential actions.

## Financing / hiring

Do not assume a USD 3–5M seed is justified from internal CI and two-host drills. Start with hands-on independent security review, part-time protocol/production engineering, and founder-led design-partner interviews. Prioritize a developer advocate and sales executive only if adoption and paid pilots support those roles. Incorporation and IP assignment should be guided by an actual fundraising/contracting need and qualified legal advice, not as an unconditional this-week milestone.

**Verdict:** BUILD scoped evidence/authorization developer alpha; INVESTIGATE customer willingness to pay and technical defensibility; WATCH clearinghouse/M2M commerce concept pending verified ecosystem demand.
