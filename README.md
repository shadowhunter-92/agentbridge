# AgentBridge — the Meta-Bridge

**One neutral mesh every agent speaks through: translate, route, verify, govern.**
Any protocol in, any protocol out — with identity, budgets, and a tamper-evident audit trail
built into the call path.

> Status: working prototype. 6 protocols live + conformance-tested against real SDKs, a
> governance moat, and an HTTP control plane. Business demand still being validated
> (see `docs/MOM_TEST_TARGETS.md`). Honest assessment lives in `docs/`.

## What it does
- **N-protocol mesh (any-to-any):** MCP (Anthropic), A2A (Google/LF), ACP (IBM/LF), OpenAI
  function-calling, Gemini function-calling, AGNTCY ACP. One canonical model → adding a protocol
  is one adapter, not N² mappings. Every adapter is validated against the protocol's **real
  official SDK**.
- **In-line proxy:** the bridge actually sits *between* live agents on different protocols, not
  just translating (see `examples/`).
- **Governance plane (the moat):** Ed25519 agent identities (DIDs), per-agent spend/rate budgets,
  human-in-the-loop approvals for sensitive capabilities, and a hash-chained tamper-evident audit
  trail — all **enforced in the call path** and **durable** (SQLite; Postgres-swappable).
- **Drop-in MCP server:** point Claude Desktop / an IDE / a gateway at it to reach other protocols.

## Quick start
```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (Windows; use bin/ on *nix)

# Run the meta-bridge control plane (mesh + governance)
uvicorn src.api.control_plane:app          # docs at http://localhost:8000/docs
#   set AGENTBRIDGE_ADMIN_KEY for operator endpoints; AGENTBRIDGE_DB=/path.db for durable governance

# Or run it as a drop-in MCP server (stdio)
python -m src.serve.mcp_gateway

# See the live demos (real agents on both ends)
.venv/Scripts/python examples/live_nprotocol_proxy.py   # OpenAI/ACP -> live MCP, MCP -> live ACP
.venv/Scripts/python examples/live_governed_proxy.py    # identity + budget + audit in action

# Tests
.venv/Scripts/python -m pytest tests/ -q                # 169 passing
```

## Architecture
- `src/protocols/` — canonical hub + per-protocol adapters (the mesh)
- `src/governance/` — identity, audit, budgets, approvals, policy, gateway, persistence (the moat)
- `src/proxy/` — real transport clients + in-line proxy
- `src/api/control_plane.py` — the shipped HTTP API (mesh + governed routing, authenticated)
- `src/serve/mcp_gateway.py` — drop-in MCP server packaging
- `src/api/api.py` — **legacy** MCP↔A2A-only app (deprecated; kept for back-compat tests)

## Security model
- **Operator endpoints** require an admin key (`X-Admin-Key`).
- **Agent endpoints** require Ed25519 **signed requests** (`X-Agent-Id`/`X-Nonce`/`X-Signature`)
  with nonce replay protection. Identities can be revoked.
- Audit is hash-chained and tamper-evident; export via `/control/audit/export`.

## Docs (read these — honest, no hype)
`docs/VISION_META_BRIDGE.md`, `docs/PROTOCOL_SUPPORT.md`, `docs/GOVERNANCE.md`,
`docs/DEMAND_VALIDATION.md`, `docs/MOM_TEST_KIT.md` + `docs/MOM_TEST_TARGETS.md`,
`docs/DEEP_REVIEW_2026-06-06.md`, `docs/PROJECT_STATE.md`.

## License
Apache 2.0
