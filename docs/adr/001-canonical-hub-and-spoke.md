# ADR-001: Canonical Hub-and-Spoke Model for Protocol Translation

## Status
Accepted

## Context

AgentBridge needs to support N protocols (MCP, A2A, ACP, OpenAI, Gemini, AGNTCY, etc.). The naive approach is to write N² pairwise translators (every protocol to every other protocol). For 6 protocols, that's 36 adapters. For 10 protocols, it's 100.

## Decision

We will use a **canonical hub-and-spoke model**:

1. Define a single **canonical intermediate representation** (`CanonicalCall`, `CanonicalResult`)
2. Each protocol implements **4 methods**:
   - `to_canonical_call(wire)` → `CanonicalCall`
   - `from_canonical_call(call)` → wire
   - `to_canonical_result(wire)` → `CanonicalResult`
   - `from_canonical_result(result)` → wire
3. Translation goes: `source_wire → canonical → target_wire`

Adding a new protocol requires:
- 1 adapter file (4 methods)
- 1 registry entry
- The any-to-any matrix picks it up automatically

## Consequences

### Positive
- Adding a protocol is O(1), not O(N²)
- With 6 protocols, we have 6 adapters instead of 36
- Test matrix is manageable (test each adapter's conformance, not every pair)
- Central place to add cross-cutting concerns (logging, metrics, validation)

### Negative
- Extra serialization step (source → canonical → target) adds slight overhead (~5-30 µs, negligible for most use cases)
- The canonical model must be expressive enough to capture all protocol features
- Risk of "lowest common denominator" if one protocol is too different

### Neutral
- All existing adapters must be validated against the canonical model
- The canonical model is versioned and can evolve
