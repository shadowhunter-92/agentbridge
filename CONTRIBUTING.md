# Contributing to AgentBridge

Thanks for your interest — this is an early-stage, honestly-labeled work in progress,
and feedback or PRs are very welcome.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Windows; use bin/ on macOS/Linux
.venv/Scripts/python -m pytest tests/ -q          # 150 passing; 156 with a Postgres DB (6 PG tests skip without one)

# To run the 6 Postgres integration tests (incl. multi-worker concurrency), point them at a throwaway DB:
#   docker run -d --name pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=agentbridge_test -p 5544:5432 postgres:16
#   $env:AGENTBRIDGE_TEST_PG = "postgresql://postgres:pw@localhost:5544/agentbridge_test"   # PowerShell
#   .venv/Scripts/python -m pytest tests/test_postgres_store.py -v
.venv/Scripts/python examples/demo_story.py       # the whole product in one screen
```

## Ground rules

- **Conformance first.** Every protocol adapter is validated against that protocol's
  *real* official SDK type, not just a hand-written schema. New protocol work must keep
  that discipline (the SDKs disagree on field names in ways that silently break bridges).
- **Tests are required.** Add tests with any behaviour change; keep the suite green.
- **Fail loudly, not silently.** Malformed input should raise a clear, protocol-named
  error (`MalformedWireError`), never a confusing empty value.
- **No secrets in commits.** `.env`, keys, and `*.db` are gitignored — keep it that way.

## Adding a protocol (the recipe)

1. Add `src/protocols/<name>.py` implementing `ProtocolAdapter` (four to/from-canonical
   methods); guard `to_canonical_call` with `require_mapping(wire, self.name)`.
2. Register it in `src/protocols/registry.py`.
3. Add a conformance case in `tests/test_protocols_conformance.py` validating output
   against the protocol's real SDK type; the any-to-any matrix picks it up automatically.
4. If it has a runnable server, add `examples/<name>_server_agent.py` + a live route.

See `docs/PROTOCOL_SUPPORT.md` for the architecture and `docs/ROADMAP.md` for what's
planned vs deliberately deferred.

## Pull requests

- Keep them focused and small where possible.
- Describe *why*, not just *what*.
- Run the full test suite and the demo before opening the PR.

## License

By contributing you agree your contributions are licensed under the repository's
**Apache 2.0** license.
