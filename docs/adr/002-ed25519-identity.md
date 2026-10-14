# ADR-002: Ed25519 for Agent Identity

## Status
Accepted design, with the current wire clarification below (October 14, 2026).

## Context

AgentBridge needs a way to verify that a call actually came from a specific agent. We need:
- Non-repudiation (agent can't deny they made the call)
- Replay protection (can't reuse an old signature)
- No central authority (decentralized, like blockchain wallets)
- Fast verification (sub-millisecond)

## Decision

Use **Ed25519** digital signatures for agent identity:

1. Each agent generates an Ed25519 key pair on registration
2. The public key is stored as the agent's DID (Decentralized Identifier)
3. Every call includes: `agent_id`, `nonce` (timestamp or UUID), `signature` (Ed25519 over `agent_id + nonce + body`)
4. The server verifies the signature against the stored public key

## Consequences

### Positive
- Ed25519 is fast (~0.1 ms per verification)
- Keys are small (32 bytes)
- Signatures are small (64 bytes)
- No central certificate authority needed
- Widely supported (libsodium, cryptography, OpenSSL)

### Negative
- Agents must manage their private keys (key rotation is manual)
- If a private key is leaked, the attacker can impersonate the agent until the key is revoked
- No recovery mechanism if an agent loses their private key

### Neutral
- The identity system is separate from the governance system (you can have identity without budgets, or budgets without identity)
- Key rotation is supported but requires manual steps

## Current request contract and limits

Use `src.governance.request_auth.sign_request` rather than constructing an
ambiguous concatenation. It signs the UTF-8 encoding of
`agent_id + "\n" + nonce + "\n" + SHA256(raw_body).hexdigest()`.
Production nonces use `<unix-time-seconds>:<random>` with a bounded time window
and an atomic shared-SQL nonce claim. Development UUID examples do not describe
the production anti-replay contract.

A signature establishes possession of the enrolled key. It does not establish
human intent, legal non-repudiation, independent key custody or action fulfillment.
Agent registration/revocation and operator trust remain explicit authority.
