# Bounded sandbox independent-readback demonstration

The test `tests/test_sandbox_readback_lost_ack.py` exercises the first end-to-end
trust/evidence proof-of-concept. It uses two separately generated Ed25519 keys,
a persistent sandbox destination SQLite file and an independent read-only SQLite
connection. It deliberately simulates the response being lost **after** the
destination transaction commits.

## Execution and expected invariants

1. Allocate a durable operation ID and reserve the governed budget.
2. The sandbox destination writes one idempotent operation to persistent state,
   signs its receipt and commits.
3. The test drops the acknowledgment after the commit. The governance ledger
   remains `unknown`; repeated writes and ledger claims are refused.
4. An observer independently connects to authoritative sandbox state using
   SQLite `mode=ro` and `query_only=ON`. A missing row remains unknown;
   never assert failed on absence.
5. The observer verifies the persisted destination receipt with a pinned
   destination public key, then signs a separate operation-bound statement.
6. `Reconciliation.record` requires both signed statements in production
   mode, rejects altered/absent readbacks and settles the original SQL budget
   reservation exactly once.
7. Regression tests assert only one destination-side effect and that the
   settled ledger and budget agree.

## Run

```bash
python -m pytest -q tests/test_sandbox_readback_lost_ack.py
```

This is a **sandbox-only demonstration**. Separate SQLite connections,
independent private keys and read-only flags are meaningful isolation
properties of this test, but both signers and databases remain within one
test-run trust domain. A real target's operator must control and attest
authoritative observations, observe source permissions, enforce per-tenant
identity and operate a separate readback service with real read-only
credentials. DNS/egress policy, adversarial deployment testing, immutable
checkpoint anchoring, key rotation and professional review are still open.

Do not claim this constitutes independent customer-system verification,
exactly-once execution, A2A/MCP full conformance, or production qualification.

## Four-product path

- **OSS:** reusable destination/readback verifier and sandbox reference adapter.
- **Trust:** no automatic retry after lost ACK, durable operation key and settlement.
- **Evidence:** independently signed observer statement linked to the receipt.
- **Enterprise:** future managed verifier and immutable archival infrastructure,
  only after isolated deployment and commercial validation.

This work closes the **synthetic sandbox readback milestone**, not the entire
trusted execution or seven-gate production release.
