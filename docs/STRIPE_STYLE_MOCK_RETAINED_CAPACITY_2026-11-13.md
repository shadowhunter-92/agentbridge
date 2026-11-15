# Offline Stripe-style mock retained capacity — November 13–15, 2026

Started November 13; runtime tests executed November 14; final local review and
documentation completed November 15, 2026. This extends the
[offline reference contract](OFFLINE_STRIPE_STYLE_CONTRACT_2026-11-12.md).
Engineering alpha, local SQLite example only; production remains NO-GO.

## Source and API

Base commit: `f309a35cb5c3ec4164acea5ba2622dc04be6807c`, tree
`17fd9e48708ebed43971a4d0b53b9e6cf703c609`. Local branch:
`fix/stripe-mock-retained-capacity-2026-11-13`.

The example reuses `FencedSqliteTarget`, the read-only observer and existing
evidence verifier. No `src/` production path, dependency, workflow, license or
CODEOWNERS changes are included. This is a source-checkout example, not a new
installed SDK or provider adapter. It uses no Stripe account, object, key,
SDK, credentials, network or money movement, and establishes no Stripe fencing
or provider retention guarantee.

`MockStorageLimits(max_records=10_000, max_bytes=16*1024*1024,
max_entry_bytes=64*1024)` sets one immutable policy per destination SQLite file.
Both `StripeStyleMock(..., limits=policy)` and
`WebhookInbox(path, limits=policy)` accept it. Exact positive integers are
required; ceilings are 100,000 records, 512 MiB aggregate and 1 MiB per entry,
with entry bytes no greater than aggregate bytes.

On first installation, omitted limits install those defaults. On reopen,
omitted limits adopt the persisted policy; explicit limits must match it
exactly. Looser and stricter replacement configurations both refuse. Each
handle's `capacity()` returns the three limits plus `used_records` and
`used_bytes` in one read transaction. It reports storage usage; it grants no
authorization and reserves no future space.

## Aggregate accounting and integrity

One record budget and one byte budget cover all rows across
`mock_stripe_attempts`, `sandbox_effects` and `mock_stripe_webhooks`, including
effects inserted through the existing compatible v1 destination writer.
For every row, byte usage is the sum of **all** stored scalar and BLOB column
bytes, including repeated identifiers, fingerprints, hashes and receipt
signatures. Text counts its actual SQLite UTF-8 bytes; JSON counts its stored
serialization, not original wire formatting or character count. The per-entry
limit applies to that whole row. A payment normally retains two records;
a distinct inbox notification retains one.

Capacity is derived from immutable retained rows, following the existing
signing-journal pattern. There is no mutable usage counter to drift or reset.
The persisted policy and payload rows reject UPDATE, DELETE and replacement.
AFTER INSERT guards validate stored types and aggregate/per-entry limits and
abort the insertion if any limit would be exceeded. The existing destination
checks its fence and inserts its effect under its own `BEGIN IMMEDIATE` write
transaction. Mock attempts and inbox entries also use `BEGIN IMMEDIATE`, so
separate connections compete against one serialized aggregate budget.
Committed payload usage is monotone while these guards remain installed.

Existing compatible unbounded example history is counted during the initial
transaction; malformed historical types or over-limit history refuse without
deleting history or installing a partial policy. An installed policy with a
missing or changed payload table/guard refuses reopening and further mock
writes rather than healing or resetting it. Reserved TEMP objects, attached
namespaces, UTF-16 files and queued-v2 destination files are outside this
contract and are refused. This is one local mock namespace, not tenant
isolation or a PostgreSQL backend.

## Saturation and UNKNOWN

Saturation rolls back the new insertion and preserves earlier attempts,
effects, notification deduplication and request argument bindings. An identical
already-retained notification can still acknowledge a duplicate at capacity;
changed content under the same event ID refuses. An existing mock attempt
still requires readback and refuses every resend, including after restart.
There is no eviction, garbage collection, capacity refund or automatic replay.

The original two-commit boundary is deliberate: durable attempt first, fenced
effect second. This unit does **not** reserve space for a future effect. Another
writer can consume the remaining budget between those commits; an effect can
also exceed its per-entry limit after its attempt fits. That refusal leaves the
attempt retained and UNKNOWN with zero observed effects. It does not certify
safe failure or permit a resend. A lost acknowledgment after a successful
effect likewise preserves UNKNOWN in the separate governance ledger until an
explicit existing reconciliation path is used. Tests verify that the original
reservation and budget remain unchanged. Storage capacity is not another
commercial spending budget.

Signed readback of existing effects remains available at saturation. Readback
validates the existing request/effect evidence, not capacity completeness; it
does not recreate guards or change accounting. All keys and files still share
one local test trust domain, without independent customer-system custody.
The mock has no legal-hold API and this unit adds none. Retaining every payload
row is not legal-hold management, an archival policy or a compliance conclusion.

## Qualification and retained receipts

The final runtime freeze passed **151 tests in 12.77 seconds**, with no skips or
failures, on Windows and Python 3.12.10 using the existing venv. The run began
`2026-11-14T08:35:24.5603049Z` and ended
`2026-11-14T08:35:39.3213429Z`. Counts are 82 existing/extended mock cases,
62 capacity cases and 7 existing destination/readback/evidence regression
cases. Coverage includes ordinary success, exact byte boundaries, invalid and
loosened policy, restart adoption, NULL/type rejection, UTF-8 bytes, duplicate
and replacement refusal, schema/guard loss, namespace shadows, lost ACK at
capacity, unchanged UNKNOWN exposure, parallel count/byte collisions, two
parallel payments and competing inbox/payment commits.

The six test modules were `tests/test_stripe_style_mock.py`,
`tests/test_stripe_style_mock_capacity.py`,
`tests/test_fenced_sqlite_destination.py`,
`tests/test_sandbox_readback_lost_ack.py`,
`tests/test_external_evidence_verifier.py` and `tests/test_trust_sdk_evidence.py`.
The command used `python -B -m pytest`, explicit pytest-asyncio/timeout plugins,
plugin autoload disabled, and fresh pytest base-temp/cache/JUnit paths.
The mock tests prohibit socket construction, DNS and connection calls.

Final tested source SHA-256 values, unchanged before and after the run:

| File | SHA-256 |
| --- | --- |
| `examples/stripe_style_mock.py` | `498f9864062ff698d3974fc9b2e656682cddcc1a66b2ced4fbcf9cc319cb093c` |
| `tests/test_stripe_style_mock.py` | `ffefe052c3123d85f484ce90dc6d83ce4794d278659f609092b91187bb95adb3` |
| `tests/test_stripe_style_mock_capacity.py` | `1fbce6339cb3b5d8b6c5f634f7cdb6ce344ee79d0798f09112e0a32e45949728` |

Operator-local evidence is retained under
`work/stripe-mock-capacity-evidence-20261113/` in the coordinating workspace.
`attempt1` preserves an argument-format usage failure (exit 4, no collection);
`attempt2` preserves the earlier 133-pass freeze before the final edge cases;
`attempt3` preserves the exact final argument array, stdout/stderr, JUnit,
timestamps and before/after source hashes. The final local receipt also pins
the commit/tree and documentation validation. These local receipts are not
hosted CI or independently held evidence. No PostgreSQL, Python 3.11, provider,
wheel-install or full-repository acceptance is claimed for this unit.

## Remaining limits

These are logical retained payload bounds, not a physical disk quota. SQLite
pages, indexes, journals/WAL, temporary space, fixed policy/binding metadata,
fence metadata, unrelated tables and administrative writes are outside the byte
account. The mock API uses one bound fence scope; this unit does not constrain
arbitrary direct callers adding other scopes or tables. Database/file/DDL
owners and trusted in-process code remain trusted; schema qualification is
not a hostile SQL sandbox, rollback witness or file-replacement detector.
There is no global cap across multiple database files. Aggregate scans are
linear in retained history, with no performance or availability SLO. This
remains an offline bounded demonstration, not a public webhook listener,
production service or real external-destination acceptance.
