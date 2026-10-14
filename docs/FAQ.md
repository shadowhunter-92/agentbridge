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
from src.integrations import translate_tool_call

# Pure tool-call translation; no network execution or governance
target_wire = translate_tool_call("add", {"a": 2, "b": 3}, to="mcp")
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
translated = default_registry.translate_call(wire_data, "mcp", "a2a")
```

### Q: How do I set a budget?

```bash
# Via the API (as admin)
curl -X PUT http://localhost:8000/control/budgets/agent_42 \
  -H "X-Admin-Key: $AGENTBRIDGE_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"spend_limit": 10.0, "rate_limit": 100}'
```

### Q: How do I see the audit log?

```bash
# Via the API (as admin)
curl http://localhost:8000/control/audit \
  -H "X-Admin-Key: $AGENTBRIDGE_ADMIN_KEY"
```

Or inspect the SQLite file directly:
```bash
sqlite3 agentbridge.db "SELECT * FROM audit;"
```

---

## Deployment

### Q: Can I run AgentBridge on AWS Lambda?

AgentBridge is designed for long-running processes (FastAPI + uvicorn). For AWS Lambda, you'd need to:
1. Use an ASGI adapter like `mangum`
2. Use a supported PostgreSQL backend instead of local SQLite; a DynamoDB backend is not implemented
3. Consider cold-start latency

This is not currently a first-class deployment target, but it could work with adaptation.

### Q: Can I run it on Kubernetes?

**Yes.** The Dockerfile is designed for containerized deployment. Use a `StatefulSet` if you need persistent SQLite, or a `Deployment` with a Postgres `AGENTBRIDGE_DB` URL.

### Q: How many workers can I run?

- **In-memory store:** Single worker only — per-process, so the audit chain would fork across processes
- **SQLite:** Tested local workers on one local DB file using `BEGIN IMMEDIATE` and WAL; this does not qualify shared network filesystems or distributed HA
- **Postgres:** Tested shared-database workers using atomic operations and advisory locks; automated split-brain-safe HA is not qualified

### Q: Does it work behind a reverse proxy?

**Yes, and it's recommended.** The control plane expects TLS to be terminated at nginx, Caddy, or Cloudflare. The app itself runs HTTP.

---

## Performance

### Q: What performance has been qualified?

The repository contains synthetic translation, SQL concurrency and bounded
Trust/Evidence benchmarks. Their environments and workloads differ; their
numbers are not a full HTTP-to-destination-to-authoritative-readback service SLO.
Run the documented benchmarks on the exact commit and record latency tails,
errors, throughput and resources. Sustained production-shaped overload and
failure acceptance remain open. See [performance baseline](PERFORMANCE_BASELINE_2026.md)
and [handoff register](HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md).

---

## Troubleshooting

### Q: Tests fail with `ImportError: cannot import name '...' from 'mcp'`

The MCP SDK is rapidly evolving. Make sure you have the correct version:

```bash
python -m pip install -r requirements-protocols.txt
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
