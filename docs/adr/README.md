# Architecture Decision Records (ADRs)

This directory contains records of important architectural decisions made in AgentBridge.

## What is an ADR?

An Architecture Decision Record (ADR) captures an important architectural decision made along with its context and consequences. It helps future maintainers understand why a decision was made, not just what was decided.

## ADRs

| ADR | Date | Title | Status |
|-----|------|-------|--------|
| 001 | 2024-06-01 | Canonical Hub-and-Spoke Model | Accepted |
| 002 | 2024-06-15 | Ed25519 for Agent Identity | Accepted |
| 003 | 2024-06-15 | SHA-256 Hash Chain for Audit | Accepted |
| 004 | 2024-06-15 | SQLite + Postgres Dual Persistence | Accepted |
| 005 | 2024-06-15 | In-Memory Approval Queue (for now) | Accepted |
| 006 | 2024-06-15 | Optional Governance (opt-in) | Accepted |

## Template

To create a new ADR, copy this template and fill it in:

```markdown
# ADR-XXX: Title

## Status
- Proposed / Accepted / Deprecated / Superseded by ADR-YYY

## Context
What is the problem we're trying to solve?

## Decision
What did we decide to do?

## Consequences
- Positive: What benefits does this bring?
- Negative: What trade-offs or costs are there?
- Neutral: What changes for users or contributors?
```
