# AgentBridge audit register — October 13, 2026

**Scope:** inventory and reconciliations of live GitHub branches, CI, security/trust code and commercial follow-up. **Not** an independent code audit, license opinion, production sign-off or completed market validation.

## Verified live baseline

- `main` remains experimental and separate from draft integration [PR #41](https://github.com/shadowhunter-92/agentbridge/pull/41).
- Integration head before this audit: `3ad0702c6bf5aaf1676af88724956fdb2af38788`. Its latest 7 named workflows passed: full CI, CNI, Evidence/Trust, inline-proxy fail-closed, governance, AWS offline preflight and two-host harness static safety.
- GitHub ruleset `25007045` is active for main/release/integration; no force-pushes/deletion, mandatory PR, Python 3.11/3.12 checks, but **zero mandatory approving reviews**, with admin bypass.
- The independent AWS two-host run is a narrowly scoped experiment, not a general high-assurance destination certification.

## Branch reconciliation inventory

There were **24 Git branches and 9 open pull requests** at audit start. Ancestry comparison against integration confirmed these 0-unique-commit ancestors:
`release/r4-internal-gates-2026-10`, `release/rc0-hardening-and-validation-2026-10`,
`engineering/production-hardening-2026-10`, `engineering/r1-r2-trust-execution-2026-10`,
`engineering/r3-reconciliation-audit-2026-10`, `engineering/r3-staging-faults-2026-10`,
`reconcile/main-into-r4-oct2026`.

**Do not delete branches solely because they are ancestors:** draft PR #34 still points to the release branch, and protection policies apply to release branches. Preserve provenance and allow human review of archiving. The `prod/readiness-pass` line contains **5 unique commits** and changes to OIDC, controls, durability, metrics, configuration and tests. It must be inspected and selectively reconciled, not blindly merged. Other squash-merged feature heads may appear divergent because ancestry was not preserved; verify tree content before deleting. Dependency-bot PRs require independent security and lock tests.

## Genuine code risks identified

1. The older inline proxy previously translated unsupported MCP/A2A procedures into tool actions. This was addressed in [PR #48](https://github.com/shadowhunter-92/agentbridge/pull/48), merged into integration with test coverage, not merged into main.
2. The legacy `src/engine/translation_engine.py` still implements broader implicit fallback/conversion than the limited canonical `src/protocols/` subset. Do not expose it as a policy enforcement boundary; perform path-by-path deny checks before privileged dispatch.
3. Protocol scope remains single-shot MCP `tools/call` and limited A2A actions; async task lifecycle, streaming, cancellation/resume and official version-specific transports are not certified.
4. Test numbers and performance statements in older `docs/ROADMAP.md` are stale and internally inconsistent with recent 13-job CI and performance measurements. Never equate a passing job count with an exhaustive test count.
5. `docs/ENTERPRISE.md` has optimistic general cross-worker scaling language and historical notes about an in-process approval queue. Deployment qualification must be matched to current durable approval implementation, source version and exact backend.
6. Real-third-party non-bypassable enforcement, independent signature/readback custody, active mTLS egress on external infrastructure, partition-safe automatic failover and published release provenance remain unaccepted.
7. Python overhead vs Kong/Envoy is unknown absent comparable end-to-end measurements. Do not rewrite hot path solely on speculation.
8. Existing Apache-2.0 grants survive; there is no defensible entitlement to relicense prior public source by a unilateral filename change.

## Competition gap

The initial gateway comparison omitted `agentgateway/agentgateway`, `chidhvilasa/agentgate`, `Zandmann/agentsig-core`, `dembovvski/agentledger`, and `piqrypt/aiss-standard`. These are adjacent, not all equivalent feature competitors. Their public self-descriptions suggest capabilities in MCP/A2A-aware routing, policy and/or independently verifiable cryptographic records. **Specific feature coverage and independent security have NOT been benchmarked.** AgentBridge should position as a supervised, integrable action-outcome/reconciliation component, not claim exclusivity.

## Recruiting activity (all sent, no acceptance claimed)

On October 13, five individual interview invitations were sent to published professional addresses of Vick Anand (finance leadership), Robert Kehoe (AI security/CTO adviser), Siah Burke (enterprise AI security), James Sperring (AI governance), and Raja Kathiresan (fintech payments architecture). One third technical-evaluator invitation was sent to Christian Schneider (agentic security). Previously sent follow-ups to Steven Landow and John Howard remain unaccepted. **Sent is not a meeting, reply, review, design partner or buyer commitment.** Expert/consultant views are valuable but **are not substitutes for budget-owning users**; recruit actual finance/platform budget owners after these initial conversations.

## Execution backlog

**Internal P0:** remove legacy permissive action mapping from all privileged call paths; model long-running lifecycle separately from single-shot calls; add malformed-wire/SSRF and direct-egress bypass tests; verify role/key state through externally provided public roots; enforce wheel/release signing and key rotation separately from source.
**Internal P1:** extract relevant changes from `prod/readiness-pass` selectively with tests; run comparable HTTP+auth+DB+target concurrency and bounded load shed; pin protocol transport test matrix and document unsupported features; improve outdated docs; maintain branch/CI reconciliation.
**External P0:** third-party destination owner and independently administered observer with revocation/retention; qualified mTLS/CNI environment and operator; independent security report. **External commercial:** three returned SDK reports, five completed interview notes (including budget owners) and a signed supervised pilot.
**Decision:** engineering-alpha **BUILD**, financial-grade production **NO-GO**.
