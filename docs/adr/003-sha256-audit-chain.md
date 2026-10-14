# ADR-003: SHA-256 Hash Chain for Audit Trail

## Status
Accepted hash-chain building block; assurance corrected October 14, 2026.

## Context

The governance plane requires a tamper-evident audit trail. A bare hash chain detects broken links and changed records when explicitly verified. A database owner can recompute a self-consistent chain or restore an old valid copy; detection requires an independently trusted, current checkpoint/witness anchor.

## Decision

Use a **SHA-256 hash chain** for the audit log:

1. Each `AuditEntry` includes sequence, timestamp, actor, action, protocols, capability, decision, reason, cost and `prev_hash`.
2. `compute_hash` hashes the sorted-key JSON payload, including `prev_hash` and excluding `entry_hash`.
3. Genesis uses sequence zero and a 64-character zero `prev_hash`.
4. `verify_integrity` / `verify_durable` explicitly verify sequence, links and entry hashes. Ordinary `entries` / export do not automatically verify every read.

## Consequences

### Positive
- Explicit verification detects inconsistent record changes; independently pinned witnesses are required to detect recomputed history or rollback
- No external dependencies (SHA-256 is in Python stdlib)
- Chain verification is fast (O(n) where n is audit log size)
- Append-only operation is atomic at the store level

### Negative
- The chain is linear — no branching or parallelization of appends
- Verification requires reading the entire chain (could be slow for very large logs)
- Does not prevent deletion, recomputation or rollback by a database owner; use independently retained current witness evidence and controlled custody

### Neutral
- Periodic "checkpoint" entries can be added for faster verification
- The chain can be exported to external systems (SIEM, blockchain) for additional protection

## Current retention boundary

Production audit deletion is disabled at both the high-level API and durable
SQL-store deletion boundary for `prod` and `production`. Development retention
must respect durable legal holds in the same deletion transaction. Checkpoint
signature validation authenticates a signer statement; it does not establish
independent archive custody, legal compliance or trustworthy physical outcomes.
See `src/governance/external_anchor.py` and the current handoff register.
