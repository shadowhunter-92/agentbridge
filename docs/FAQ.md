# Frequently Asked Questions

## Getting Started

### Q: Do I need a database to run AgentBridge?

**No.** AgentBridge works out of the box with an in-memory store. If you just want to translate between protocols, no database is needed.

If you want **governance features** (identity, budget, audit) to persist across restarts, set `AGENTBRIDGE_DB` to a SQLite path or a postgres:// URL:

```bash
export AGENTBRIDGE_DB=agentbridge.db
uvicorn src.api.control_plane:app
```

### Q: Can I run AgentBridge without Docker?

**Yes.** Docker is optional. The fastest way is:

```bash
pip install -e ".[dev]"
make serve
```

### Q: What Python version do I need?

Python 3.11 or higher. Tested on 3.11 and 3.12.

---

## Protocols

### Q: What is "MCP"?

[MCP](https://modelcontextprotocol.io/) (Model Context Protocol) is Anthropic's protocol for connecting LLMs to tools and data sources. AgentBridge supports it as both a source and target protocol.

### Q: What is "A2A"?

[A2A](https://github.com/a2a-protocol) (Agent-to-Agent Protocol) is the Linux Foundation's protocol for direct agent-to-agent communication, led by Google.

### Q: Can I add a new protocol?

**Yes.** See `CONTRIBUTING.md` for the recipe. In short:
1. Add `src/protocols/<name>.py` implementing `ProtocolAdapter`
2. Register it in `src/protocols/registry.py`
3. Add a conformance test in `tests/test_protocols_conformance.py`

### Q: Does it work with LangChain?

**Yes.** Use the `bridge_tool_call` helper from `src/integrations/`:

```python
from src.integrations import bridge_tool_call

# LangChain agent calls this like a normal tool
result = bridge_tool_call(tool_name, arguments, target_protocol="mcp")
```

See `docs/INTEGRATIONS.md` for details.

---

## Governance

### Q: What is the "governance plane"?

The governance plane is the set of features that control *who* can call *what*, *how much* it costs, and *what* was done. It includes:

- **Identity:** Every agent gets an Ed25519 DID (like a crypto wallet address)
- **Budget:** Per-agent spend caps (e.g., "$10 per day")
- **Approval:** Human-in-the-loop for expensive or risky calls
- **Audit:** Tamper-evident log of every call (SHA-256 chain)
- **Policy:** Declarative rules (cost caps, business hours, capability allow/deny)

### Q: Is governance mandatory?

**No.** It's strictly opt-in. The mesh works with zero governance:

```python
from src.protocols import default_registry
registry.translate("mcp", "a2a", wire_data)
```

### Q: How do I set a budget?

```bash
# Via the API (as admin)
curl -X POST http://localhost:8000/ops/budgets \
  -H "X-Admin-Key: $AGENTBRIDGE_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "agent_42", "daily_limit": 10.0}'
```

### Q: How do I see the audit log?

```bash
# Via the API (as admin)
curl http://localhost:8000/ops/audit \
  -H "X-Admin-Key: $AGENTBRIDGE_ADMIN_KEY"
```

Or inspect the SQLite file directly:
```bash
sqlite3 agentbridge.db "SELECT * FROM audit_log;"
```

---

## Deployment

### Q: Can I run AgentBridge on AWS Lambda?

AgentBridge is designed for long-running processes (FastAPI + uvicorn). For AWS Lambda, you'd need to:
1. Use an ASGI adapter like `mangum`
2. Use a persistent store (DynamoDB or RDS) instead of SQLite
3. Consider cold-start latency

This is not currently a first-class deployment target, but it could work with adaptation.

### Q: Can I run it on Kubernetes?

**Yes.** The Dockerfile is designed for containerized deployment. Use a `StatefulSet` if you need persistent SQLite, or a `Deployment` with a Postgres `AGENTBRIDGE_DB` URL.

### Q: How many workers can I run?

- **In-memory store:** Single worker only (audit chain would fork)
- **SQLite:** Single worker (database file locking)
- **Postgres:** Multiple workers (atomic operations, advisory locks)

### Q: Does it work behind a reverse proxy?

**Yes, and it's recommended.** The control plane expects TLS to be terminated at nginx, Caddy, or Cloudflare. The app itself runs HTTP.

---

## Performance

### Q: How fast is the translation?

- **Translation only:** ~5–30 microseconds
- **Full governed + audited call:** ~0.4 milliseconds (sub-millisecond)

Run `make benchmark` to see numbers on your machine.

### Q: What's the overhead of governance?

For a typical call, the governance overhead is:
- Identity verification: ~0.1 ms
- Budget reserve/commit: ~0.1 ms
- Audit log append: ~0.1 ms
- Policy check: ~0.05 ms

Total: ~0.35 ms, which is negligible for most use cases.

---

## Troubleshooting

### Q: Tests fail with `ImportError: cannot import name '...' from 'mcp'`

The MCP SDK is rapidly evolving. Make sure you have the correct version:

```bash
pip install "mcp>=1.27.0"
```

If you have an older version, uninstall and reinstall.

### Q: `PermissionError: [Errno 13] Permission denied` on `.db` file

The SQLite database file is created by the user running the process. Make sure the directory is writable:

```bash
mkdir -p ~/agentbridge-data
export AGENTBRIDGE_DB=~/agentbridge-data/governance.db
```

### Q: The control plane starts but `/docs` returns 404

FastAPI auto-generates `/docs` and `/redoc`. If you're getting a 404, check:
1. You're hitting the right port (`8000` by default)
2. No reverse proxy is stripping the path
3. The app is actually running (`curl http://localhost:8000/health`)

### Q: Docker container exits immediately

Check the logs:

```bash
docker-compose logs
```

Common causes:
- Missing `AGENTBRIDGE_ADMIN_KEY` (set it in `.env` or `docker-compose.yml`)
- Port conflict (change the host port in `docker-compose.yml`)

---

## Contributing

### Q: Can I contribute a new protocol adapter?

Absolutely! See `CONTRIBUTING.md` for the recipe. Check `good first issue` labels for beginner-friendly tasks.

### Q: What license does this use?

Apache 2.0 — free for commercial use, modification, and distribution. See `LICENSE`.

### Q: Is there a Discord or Slack community?

Not yet. For now, use GitHub Issues and Discussions.

---

## Still have questions?

Open an issue on [GitHub](https://github.com/shadowhunter-92/agentbridge/issues) — we're happy to help.
