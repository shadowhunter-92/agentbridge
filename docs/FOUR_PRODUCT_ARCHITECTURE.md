# AgentBridge product architecture — one foundation, four potential offerings

**Stage:** research and engineering alpha. These are planned product packaging lines,
not four validated or independently deployable products.

## Shared foundation

Keep `src/governance/` as the single source of authority for request-bound
identity, policy, approval, idempotency, execution states, receipt verification,
readback attestation and audit trust. Keep protocol adapters separate under
`src/protocols/`. Do not duplicate cryptographic policy logic for a managed tier.

## 1. AgentBridge OSS — free developer core

Developer-installed Python components, examples, interoperability adapters,
offline receipt/readback verification and the narrow Trust SDK.

**First gate:** documented install from a wheel, no gateway required, reproducible
one-action example, external contributors can run tests from scratch.

## 2. AgentBridge Trust — enforcement

Request-specific authorization, exact-action approval, target allowlisting,
budget reservation, durable operation state and conservative no-replay behavior.

**First gate:** one real bounded workflow handles denied, permitted, lost-ack,
crash, and reconciled operation cases without duplicate execution.

## 3. AgentBridge Evidence — proof verification and audit

Destination statement validation, independently signed state readback,
checkpoint witness validation, export, and off-database anchoring.

**First gate:** separate trust administrators and read-only authoritative
target inspection, plus retained independently retrieved witness receipts.
Cryptographic validity proves signed claims, **not** that physical/remote
execution occurred. Claims require trustworthy source observation.

## 4. AgentBridge Enterprise — potential paid operation

Federated identity, centralized controls, HA operations, security reviews,
managed evidence retention, support and contractual service objectives.

**First gate:** narrow production acceptance, then outside deployments
and a genuine paid pilot. No customer, compliance certification or SLA
is implied by the current repository.

## Release sequencing and ownership

| Sequence | We can implement and test | Cannot certify solely ourselves |
|---|---|---|
| Trust Kernel | strict auth, outcome ledger, state verification contracts, replay controls | independently administered target access and security review |
| Evidence | signed receipts, checkpoint witness verifier, portable exports, restore detection | immutable archive deployment, external witness independence |
| Compatibility | explicit supported SDK versions and feature-fidelity tests | third-party interoperability claims without counterparty testing |
| Deployment | nonroot image, SBOM, lockfiles, migration scripts, rollback rehearsals in test environment | production operational signoff and customer environment |
| Adoption | install guides, demos, example adapters, API reference | independent integrations, continued users, willingness to pay |

## Do not do

Do not split into four repositories now, assert broad MCP/A2A full compliance,
delete audit history in production, automatically retry unknown external writes,
invent a receipt standard, or replace agentgateway/ContextForge as a general
feature-for-feature gateway.

## Roadmap labels

P0–P3 denote security and production engineering/validation.
P4–P7 denote SDK, integrations, business and infrastructure growth.
The October `release/r4-internal-gates-2026-10` branch refers to an
**engineering workstream**, not completion of the R4 outside-developer
adoption milestone. Keep these meanings distinct.

## Immediate acceptance objective

A supported one-action flow must authorize the exact action, survive
interruption, remain unknown on lost acknowledgment, reconcile only
after independently sourced state evidence, and provide an independently
checkable durable audit history.

**Current verdict:** BUILD FOUNDATION; production and customer-adoption gates open.
