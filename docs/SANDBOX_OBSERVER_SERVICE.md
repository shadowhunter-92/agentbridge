# Separate-process sandbox observer: operator quickstart

**Strictly for disposable sandbox evaluation, not production.** This reference
service is deliberately disabled under AGENTBRIDGE_ENV=production. A real
deployment requires an authoritative target-specific readback adapter and
independent administration of its credentials and signing keys.

## Configuration

Create a disposable sandbox destination database through
`SandboxTarget(...).commit(...)`. Use separately generated Ed25519 signing keys
for destination and observer. Write the 32-byte **raw** observer Ed25519 private
key to a regular file with mode 0600. Write a separately generated random
bearer token of at least 32 bytes to another file with mode 0600.

Set:

- `AGENTBRIDGE_SANDBOX_DESTINATION_DB`: authoritative sandbox SQLite file.
- `AGENTBRIDGE_SANDBOX_DESTINATION_KEY_HEX`: destination public Ed25519 key.
- `AGENTBRIDGE_SANDBOX_OBSERVER_KEY_FILE`: raw observer secret key file.
- `AGENTBRIDGE_SANDBOX_OBSERVER_TOKEN_FILE`: separately provisioned bearer token.

Start via `python -m src.governance.sandbox_observer_service`. The command binds
127.0.0.1 by default and refuses non-loopback CLI binding.

`POST /v1/sandbox/readback` with
`Authorization: Bearer <token>` and the exact `agent_id`, `operation_id` and
`fingerprint`. The service independently opens the authoritative database
with SQLite read-only and `query_only`, verifies the destination-signed
persisted receipt and returns a freshly signed observer attestation.

Absent/unverified effects return HTTP 409 instead of manufacturing a
negative outcome. The response can be checked with
`src.governance.trust_sdk.verify_action_evidence`. The private observer key is
not returned.

## Current guarantees and limitations

The reference code separates invocation and observation paths and includes
authenticated negative tests. A localhost HTTP server is **not** proof of
independent host/principal isolation, nor does SQLite mode=ro establish real
cloud API read-only identity. There is no service-to-service TLS in this local
sample and no production key-enrollment/revocation protocol. Run only on a
trusted disposable machine; never expose its listener or credential files to
a network.

A production verifier needs mTLS or equivalent workload identity, operator
RBAC, restricted read-only target credentials, separate trust domain, reliable
source-of-truth semantics, rate limiting, key rotation, monitoring and full
staging review. It also needs authoritative negative-outcome semantics;
absence of an action record is not proof of failure.

Do not count this as full release-gate completion or claim customer integration.
