# Offline Stripe-style reference contract — November 12, 2026

**Locally tested example only. Engineering alpha; production remains NO-GO.**
This unit does not resolve the real external-destination qualification blocker.
It creates no Stripe object and uses no Stripe account, SDK, key or network.

## Source and integration boundary

- Base: `35f37222597341d2c23e9cd9d0baddf1e36f99f7` (PR #86 already merged).
- Local branch: `prep/stripe-style-mock-2026-11-12`.
- New files: `examples/stripe_style_mock.py`,
  `tests/test_stripe_style_mock.py` and this report. The recorded test freeze
  preceded the local unit commit; later commit/publication evidence belongs in
  the coordinating phase register. No hosted CI qualifies this unit yet.
- All 103 tracked `src/` files, existing tests, Apache-2.0 license and
  `.github/CODEOWNERS` remain unchanged. No dependency or workflow changes.
- The existing `FencedSqliteTarget`, `SandboxReadOnlyObserver` and
  `verify_action_evidence` provide effect fencing and evidence verification.
  The example adds no replacement authorization, budget or settlement kernel.

The two supplied critical-path handoffs requested a mock that could prove
Stripe fencing. That conclusion cannot follow from an offline mock. This unit
instead demonstrates the existing SQLite reference contract behind a small
PaymentIntent-shaped interface. A native Stripe destination still requires its
own reviewed contract, credentials, API trials and independent acceptance.

## Supported contract

`PaymentIntentRequest(target_id, agent_id, operation_id, amount, currency="usd")`
accepts positive integer minor-unit amounts up to 100,000,000 and USD only.
Identifiers are bounded to 128 ASCII identifier characters. Its deterministic
fingerprint binds the domain, target, agent, operation, amount and currency.
Its idempotency key binds stable target/agent/operation identity, so changing
purchase arguments cannot silently generate a new key for the same operation.

The operator binds a database to one mock target. `acquire(owner=...)` delegates
to the existing SQLite fence; `confirm(request, owner=..., epoch=...)` performs
one synthetic create-and-confirm. A permanent immutable request/attempt binding
commits before the target effect. The existing destination then checks its
current owner/epoch/expiry under its write lock, records one signed effect and
optionally drops the acknowledgment **after** that effect commits.

An existing attempt always refuses another send. Different arguments receive
a conflict; identical arguments require explicit readback. The attempt and
effect are separate local commits: a crash or fence/signing refusal between
them can leave an attempt with zero observed effects. Missing evidence stays
UNKNOWN. This example supplies no safe-failure/absence certificate, retry,
refund, cancellation or garbage collection for that case.

The returned PaymentIntent-shaped object has `object="payment_intent"`, a
`pi_mock_` identifier, `livemode=false`, amount/currency, `status="succeeded"`
and operation metadata. It is a deterministic projection of the exact request
and existing signed SQLite effect, not a Stripe object or complete
PaymentIntent state machine. Requires-action, authorization/capture, payment
methods, cancellation, refunds, failures and real settlement are unsupported.

`StripeStyleReadback.observe_payment(request)` reads the request binding and
signed destination state through a separate read-only SQLite snapshot. It
reuses the existing observer's verification and attestation. A missing,
changed or untrusted binding/effect produces no successful observation.
`verify_payment_evidence(...)` checks the exact expected projection and the
existing receipt/readback signatures against caller-pinned keys. Verification
does not dispatch, spend, reconcile or release a reservation. All local files
and generated signers still share one test trust domain; different connections
and keys do not establish independent customer-system custody.

For embedding, use these calls from the source checkout:

```python
from examples.stripe_style_mock import PaymentIntentRequest, StripeStyleMock

request = PaymentIntentRequest("payments", "buyer", "order-001", 500)
with StripeStyleMock(path, target_id="payments", sign=destination_key.sign) as mock:
    epoch = mock.acquire(owner="worker")
    intent, receipt = mock.confirm(request, owner="worker", epoch=epoch)
```

The caller owns its existing authorization/admission path. This mock does not
make an arbitrary supplied gateway fingerprint equivalent to
`request.fingerprint`; a governed demo must bind or clearly distinguish those
two domains. Major-unit governance cost versus integer minor-unit mock amount
must also be explicit. Never reserve the same commercial exposure twice.

## Webhook notification contract

`sign_webhook(raw_body, secret=..., timestamp=...)` is a synthetic fixture
signer. `WebhookInbox.accept(raw_body, signature_header, secret=..., now=...)`
checks SHA-256 HMAC over `timestamp + "." + raw_body` before parsing JSON.
Raw bytes, secret, header and timestamp are bounded. The accepted timestamp
spelling is a canonical nonnegative integer. One `t` and at least one matching
`v1` are required; multiple `v1` values and unknown header metadata are allowed.
The default freshness tolerance is 300 seconds in either direction; this
example deliberately refuses disabling the check or raising that tolerance.

The inbox accepts bounded synthetic PaymentIntent succeeded, processing and
payment-failed event envelopes with `livemode=false`. Duplicate JSON members,
nonfinite JSON, invalid signatures, stale/future timestamps, malformed events
and reused event IDs with different canonical content are refused. Legitimate
freshly signed duplicates, including equivalent JSON formatting, are acknowledged
as duplicates without another entry. Distinct out-of-order notifications are
retained without changing destination state. Concurrent duplicates insert once.

The inbox never fulfills, confirms, settles, refunds or resolves an operation.
An authenticated notification is not independent destination readback. The
synthetic fixture secret is not a Stripe webhook credential.

## Explicit differences from Stripe

- This mock keeps request/key bindings permanently and refuses even an
  identical repeated send. Stripe's v1 idempotency behavior can replay the
  cached status/body; keys may be pruned after at least 24 hours, after which
  reuse can start a new request. Validation/concurrency conflicts can occur
  before a cacheable endpoint execution. This example does not emulate those
  cache/retention boundaries or prove double-charge prevention on Stripe.
- Epoch fencing belongs to the local SQLite destination. An idempotency key
  does not establish native atomic monotonic fencing at an external provider.
- Duplicate and out-of-order webhook delivery is legitimate. Deduplication
  does not make webhooks ordered, exactly once, independent proof of delivery,
  or an automatic resolution mechanism for UNKNOWN.
- These persistent tables have no aggregate row/byte capacity or retention
  policy. This is a small-input local demonstration, not a public listener,
  scalable service, tenant isolation boundary or bounded-storage product.
  SQLite file/DDL administrators and trusted in-process code remain trusted.
- Production-mode guards refuse `AGENTBRIDGE_ENV=production` or `prod` for the
  example operations. They are defensive labels, not an isolation boundary.

Official references checked in the coordinating review:
[Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests),
[Stripe signature verification](https://docs.stripe.com/webhooks/signature),
[Stripe webhook delivery](https://docs.stripe.com/webhooks), and
[PaymentIntents](https://docs.stripe.com/payments/payment-intents).

## Local qualification and retained evidence

Final source SHA-256:

| File | SHA-256 |
| --- | --- |
| `examples/stripe_style_mock.py` | `5052bbe3dc90a9362db183d3dfd014b1e8406b74f9f87c7c3251a3eeef72d155` |
| `tests/test_stripe_style_mock.py` | `244547b11052ddc327754df570b51757b02de69e516e4ccf353e1195e42cb659` |

Final regression: **92 passed, zero failures/errors/skips/warnings, 6.27s**.
This consists of 81 new example-contract cases plus 11 existing cases from:

- `test_fenced_sqlite_destination.py`
- `test_sandbox_readback_lost_ack.py`
- `test_external_evidence_verifier.py`
- `test_readback_attestations.py`
- `test_readback_config_validation.py`

Coverage includes exact success/readback, held original budget and UNKNOWN
after lost acknowledgment, restart/no-resend, durable changed-argument refusal,
stale/wrong-owner/unauthorized-target refusal, pre-effect crash, signing failure,
parallel operation collisions, malformed requests, read-only enforcement,
corrupt destination rows, forged keys/signatures, mismatched result projections,
immutable request rows, raw-body/timestamp HMAC, duplicate/out-of-order events,
parallel webhook duplicates and production refusal. Tests use real temporary
SQLite files and Ed25519 signatures. New test cases explicitly forbid socket
creation, connection and DNS lookup; no network adapter is implemented.

Evidence root:
`C:\Users\DELL\Documents\Codex\2026-10-13\d-codex\work\stripe-style-mock-evidence-20261112`.
Final `regression5/` contains source-before/source-after pins, `junit.xml` and
`result.json`; `regression5.log` records the console result. Before/after pins
match. Interpreter: existing `D:\codex\agentbridge\.venv\Scripts\python.exe`,
Python 3.12.10, with plugin autoload disabled and explicit asyncio/timeout
plugins. The final run used a fresh scoped local permission elevation for
Windows pytest temp-directory ACLs, without modifying pytest directory modes.

Earlier attempts remain separate: attempt1 had five passes and 76 setup errors
because the explicit temp parent was absent; attempt2 hit Windows restricted-
token mode-0700 directory ACL errors. Attempt3 passed 80 earlier cases with
only fresh temporary-directory mode normalization; that shim was removed.
Regression4 passed 91 cases without the shim. A final canonical-timestamp
negative case and check produced regression5's 92 passes. No earlier result
is presented as qualification of later source.

No PostgreSQL, Stripe API, AWS, actual network fault, independent operator,
customer evaluation, hosted CI, release, publication or production qualification
is claimed. No commit, push, merge, external contact or credentials were used.
