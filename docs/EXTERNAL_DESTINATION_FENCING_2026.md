# External destination fencing: capability and acceptance - October 25, 2026

Status: **PARTIALLY TESTED**. Strict native Stripe/Salesforce execution and the two-external-destination acceptance gate are **BLOCKED**. Production remains **NO-GO**.

Baseline: `c154b28c34cfeab927753e51b93595cc1b485810`, the owner-approved PR #74 merge. Its own [push CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/40187737269) passed 16/16 jobs. The reviewed PR source `9aaf6a1a0a460d3824ad2966a57f8c5f575bdfae` separately passed 24/24 jobs across seven workflows. Those historical results do not qualify this later test/documentation unit or an external destination.

## Existing implementation and the preserved boundary

The maintained implementation already has SQL destination fencing, signed action intent, single-attempt queued dispatch, receipt verification and independently signed observations. The new work reuses these boundaries rather than defining a second authorization or evidence scheme.

| Path | Existing contract | Limitation and required next evidence |
| --- | --- | --- |
| `src/governance/queued_destination_contract.py`, `tenant_kernel.py` | Exact `queued_fenced_sqlite_v2` descriptor, configured destination and distinct signing roles | Nonproduction SQLite demonstration; other transports do not inherit qualification |
| `src/governance/queued_task_dispatch.py` | Persist the signed attempt before one adapter commit; an existing attempt enters observation/recovery | Recovery must not reacquire and resend an uncertain effect |
| `src/governance/destination_receipts.py`, `readback_attestations.py` | Bind receipt and observation to the configured action/keys/source | The queued v2 verifier is deliberately bound to the SQLite demo action/result; native SaaS JSON is not a matching signed receipt |
| `src/governance/https_readback_adapter.py` | Fixed public HTTPS origin, GET-only exact operation path, bounded response, no redirects or environment-selected proxy, destination signature verification before observer signing | Reads an operator-provided signed-receipt API; it is not a native Stripe/Salesforce client, an egress-isolation guarantee or proof of separately administered custody |
| PostgreSQL/SQLite fenced SQL destinations | Fence comparison and the controlled SQL effect can share one destination transaction | A SQL transaction does not atomically govern an unrelated SaaS call |
| `src/api/trusted_targets.py` | Current named target execution refuses production | Preserve this refusal until a specific target contract is qualified |

The synchronous transport path's returned result must not be treated as authoritative settlement of an external consequential effect. The queued operation identity, exact-action authorization, delegation, approval, accounting and UNKNOWN reservation semantics are unchanged by this unit.

## Provider capability matrix

| Destination | Current support in this phase | Fencing and idempotency semantics | Status |
| --- | --- | --- | --- |
| Stripe sandbox | Primary API contract investigated; the separate AgentBridge sandbox dashboard is available, with no API execution/readback qualification yet | Native idempotency helps bounded duplicate suppression. It does not establish an atomic check of AgentBridge's monotonic epoch, tenant/action authorization and payment effect | **BLOCKED** |
| Salesforce Developer Edition/sandbox | Primary locking contract investigated; free environment provisioning has not succeeded | A separately installed Apex transaction may be able to validate a fence and perform a Salesforce-local effect under record locks. That endpoint, schema, authorization, deployment and live concurrency behavior are not implemented or qualified here | **BLOCKED** |
| Operator-controlled generic HTTP service | Existing signed-receipt readback building block | The destination itself must compare the current epoch and enforce action identity in the same transaction as its effect. An allowlist or gateway-side lease alone cannot provide this property | **BLOCKED** |

Stripe documents that v1 idempotency keys can be pruned after they are at least 24 hours old; reuse after pruning can create a new request. Do not retry an unresolved operation merely because a key was used previously. A metadata field containing an epoch does not make Stripe enforce it. See [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests).

Salesforce documents that Apex `FOR UPDATE` locks are scoped to the transaction and released during callouts. A future operator-installed Apex fence must keep comparison and the controlled Salesforce-local effect in one transaction, handle first-row/concurrent creation, and cannot extend the lock over an unrelated remote effect. This is a proposed qualification path, not a current capability claim. See [Salesforce locking statements](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/langCon_apex_locking_statements.htm).

No new `StripePaymentDestination`, `SalesforceApiDestination` or generic mutating adapter is advertised as supported. A class that forwards writes with metadata/idempotency keys would not satisfy the required destination-side fencing contract. Account access alone would not remove this semantic blocker.

## Meaningful readback regression coverage

The previous test named `test_https_fetch_does_not_follow_redirect_and_bounds_payload` substituted a successful opener with a small body. It did not exercise the actual redirect handler or oversized-body refusal. This was a coverage defect; no runtime defect is claimed.

The test-only follow-up retains real urllib opener/response/redirect processing and substitutes only wire I/O. DNS and socket guards fail the synthetic tests if real network I/O is attempted. It covers:

- 301/302/303/307/308 redirects to a second origin, a relative path and an HTTP downgrade; one original request, no redirected credential forwarding or signing.
- Exact 32,768-byte positive signed readback and oversized 32,769/65,536-byte bodies; one read bounded to 32,769 bytes and no signature for rejection.
- Unexpected HTTP status, missing/wrong MIME type, malformed JSON/UTF-8 and invalid receipt wrappers.
- Failure during connection or body read; `ReadbackUnavailable`, no observation signature and no inferred successful/failed effect.
- Escaped operation references, explicit timeout, no environment proxy, and positive destination/observer signature verification through the real entry point.

One local invocation passed **58 distinct cases**, with zero failures, errors or skips: 52 in `tests/test_https_readback_adapter.py` and six directly required regression cases across four other modules. Local Windows working-file SHA256: `f26f6ceae7b5adb800f7ae06f44aef33aebb2d657d1bef5a29c70a74dcd41cee`. Local receipt SHA256: `f68b5ad9db37d86e9b48d44df819ed0b74b51600daa8be678619f1d0d0f69f6a`. The frozen manifest and actual pre/post maps associate the test result with unchanged runtime source. Git's CRLF-to-LF checkout normalization is recorded separately from raw local bytes. At this pre-publication snapshot, the later unit has no hosted CI result; subsequent CI must identify its own exact commit.

These are synthetic HTTP handler tests. They do not exercise provider APIs, real TLS/DNS/egress, a Kubernetes CNI, concurrent external writers, a live partition, independent credentials, physical/financial outcomes or institutional custody. They do not test queued ledger recovery or change UNKNOWN state transitions.

To reproduce the selected modules from a checkout with the repository's test dependencies installed:

```console
python -m pytest -q tests/test_https_readback_adapter.py tests/test_bounded_https_destination_contract.py tests/test_destination_receipts.py tests/test_readback_attestations.py tests/test_destination_receipt_envelope.py
```

Use the repository's controlled test environment; this command requires no provider credential or PostgreSQL fixture. The original guarded local run also pinned its source before/after, isolated inherited AgentBridge configuration and preserved JUnit, output and distinct test identities.

## Environment and operator prerequisites

Only dedicated nonproduction environments and synthetic records are in scope. Existing unrelated sandboxes must not be renamed, modified or used as a credential source. No production credentials or real money movement are authorized by this phase.

The maintainer authorized free Stripe/Salesforce environment setup. The owner subsequently created a separate AgentBridge Stripe account, and its guided setup opened a distinct **agentbridge sandbox** dashboard in test mode. Only optional dashboard preferences and entry to the sandbox were completed by the assistant. No live financial activation was submitted, key revealed/copied, API credential provisioned or provider API trial performed. The previously observed disabled controls belonged to an unrelated account and do not establish a restriction on this new environment. Salesforce provisioning still returned the vendor's generic error after its verification challenge; no specific cause or successful activation was supplied. Do not infer an email-domain or country restriction from that generic error. No account identifier, identity document, secret or personal signup data belongs in this repository.

Stripe's [account setup documentation](https://docs.stripe.com/get-started/account/set-up) permits sandbox testing after account creation, before live service activation. Its [sandbox management documentation](https://docs.stripe.com/sandboxes/dashboard/manage) describes a separate sandbox created from scratch and the permitted roles. Do not activate a live financial account merely to assume it will unlock a currently disabled control. Any actual financial-account activation and identity submission must be completed by the owner with accurate eligible business details.

Before a live qualification, record:

1. The exact supported provider API version and operator-installed endpoint/schema version; mocks must use the same contract.
2. The fixed operator-controlled origin/path/allowlist, bounded timeout/body limits, and deployment egress policy. Keep credentials out of URLs/logs and source control.
3. Minimum required credential scopes and distinct destination and read-only observer administration. Creation or access expansion needs the applicable owner approval.
4. The target-side atomic action/epoch contract, expiry, revocation and tenant bindings; native idempotency retention limits and the behavior after key expiry.
5. Actual independently verified readback for the exact operation/fingerprint. An observer signs its observation, not a statement that the provider supplied an AgentBridge signing key.
6. Cleanup, resource/time/cost limits and the evidence-retention/hold requirements. No automatic retry may be used to resolve an uncertain remote effect.

## Remaining acceptance and ownership

| Requirement | Status | Responsible party | Next evidence/action |
| --- | --- | --- | --- |
| Existing ingress/dispatch/evidence contract audit | **PARTIALLY TESTED** | Internal engineering | Preserve source/test association and review the eventual versioned extension |
| HTTPS negative coverage | **PARTIALLY TESTED** | Internal engineering | Exact-head hosted CI after review/publication of this narrow unit |
| At least two actual external fenced destinations | **BLOCKED** | Engineering and consenting destination operators | Establish enforceable capabilities first; deploy permitted sandbox endpoints and test actual competing writers |
| Stale leader, promotion, duplicate action, lost ACK and commit partition against external state | **BLOCKED** | Internal engineering with operator environment access | Run measured negative trials and authoritative readback; preserve unresolved UNKNOWN without resend |
| Separately administered destination and observer | **BLOCKED** | Consenting independent operators | Approved credential custody and returned acceptance evidence |
| Production execution / unrestricted release | **BLOCKED** | Maintainer and independent reviewers/operators | All applicable governance, network, recovery, supply-chain and acceptance gates |

Do not turn two successful provider mocks into a claim that two external services enforce monotonic fencing. Record the blocker, retain the existing production refusal and continue independent internal qualification under the [phase checklist](ENGINEERING_PHASE_PROGRESS_2026-10-24.md).
