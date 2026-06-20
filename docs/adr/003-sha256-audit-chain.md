# ADR-003: SHA-256 Hash Chain for Audit Trail

## Status
Accepted

## Context

The governance plane requires a tamper-evident audit trail. If an attacker gains access to the database, they should not be able to modify audit logs without detection.

## Decision

Use a **SHA-256 hash chain** for the audit log:

1. Each audit entry contains: `timestamp`, `agent_id`, `call`, `result`, `previous_hash`
2. The hash of entry N is: `SHA256(previous_hash + entry_N_data)`
3. The first entry has `previous_hash = 0` (genesis)
4. On read, the entire chain is verified — any modification breaks the hash chain

## Consequences

### Positive
- Tamper detection is immediate and cryptographic
- No external dependencies (SHA-256 is in Python stdlib)
- Chain verification is fast (O(n) where n is audit log size)
- Append-only operation is atomic at the store level

### Negative
- The chain is linear — no branching or parallelization of appends
- Verification requires reading the entire chain (could be slow for very large logs)
- Does not prevent deletion of the *entire* chain (only detects modification within the chain)

### Neutral
- Periodic "checkpoint" entries can be added for faster verification
- The chain can be exported to external systems (SIEM, blockchain) for additional protection
