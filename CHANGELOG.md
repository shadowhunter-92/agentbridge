# Changelog

All notable changes to AgentBridge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — production/repo hygiene
- GitHub Actions **CI** workflow: runs the test suite on Python 3.11 and 3.12 (`.github/workflows/ci.yml`).
- **`pyproject.toml`** packaging with optional extras (`[test]`, `[postgres]`, `[dev]`).
- Root **`Dockerfile`** + **`docker-compose.yml`** (one-command run; healthcheck on `/health`).
- Reference **Kubernetes** manifests (`k8s/`) — a starting point; validate against your own cluster.
- **`agentbridge` CLI** (`python -m src` or `src.cli`): `serve`, `mcp`, `translate`, `demo`, `quickstart`, `--version`.
- Static **status dashboard at `/dashboard`** — shows live `/health` and `/control/protocols` (no mock data).
- README **badges** (CI, Python 3.11/3.12, license).
- `Makefile`, `.pre-commit-config.yaml`, `.editorconfig`, `.env.example`, `MANIFEST.in`.
- `docs/FAQ.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, GitHub issue/PR templates, Dependabot config.
- `Dockerfile.dev` for development; one-line setup scripts (`scripts/install.sh|.ps1`, `scripts/run_demo.sh|.ps1`).
- `examples/README.md` (examples guide); rendered `docs/architecture.png`; `docs/adr/` (architecture decision records).
- `RELEASING.md` release checklist; `.github/FUNDING.yml` (GitHub Sponsors).
- Additional GitHub Actions — `publish.yml` (PyPI on release), `docker-publish.yml` (Docker Hub on release), `ci-manual.yml` (manual): all **dormant** (release/manual-triggered, require secrets) so they can't produce a red badge before they're configured.
- `tests/conftest.py` with reusable fixtures using the **real** governance API (replaces a hallucinated draft).

> Deliberately NOT wired yet (needs an external account/secret to function): Codecov coverage upload + badge.

### Changed
- Dependency floors bumped (pydantic ≥2.13.4, httpx ≥0.28.1) and GitHub Actions updated (checkout v7, setup-python v6) via grouped Dependabot PRs.
- **Dependabot** reconfigured to **monthly + grouped** minor/patch updates (one PR instead of ~15 at once) and to **ignore `a2a-sdk` major bumps** (1.x breaks the 0.3.x conformance tests).
- CI now prints a **coverage report** (`pytest-cov`).
- **Capped `mcp` to `>=1.27.0,<2.0.0`** and set Dependabot to ignore its major bumps. `mcp` 2.0 removed `mcp.server.fastmcp` (used by `src/serve/mcp_gateway.py` and the example server), which broke CI on an unrelated push; the cap holds the working 1.x line until the FastMCP import path is migrated deliberately.

### Fixed
- **No test can hang the suite.** Added `pytest-timeout` (90s, thread method) and hardened the threaded concurrency test (daemon workers + bounded `join`) — previously a worker stalling before the barrier could deadlock `t.join()` indefinitely.

### Tests
- `tests/test_cli.py` — CLI smoke tests (`--version`, help, a live `openai → mcp` translation). Suite now **153 passing (159 with a Postgres DB)**.

### Added — external validation
- README now documents that we do external MCP-server security reviews (OWASP Top-10 for
  Agentic Applications + MCP red-team patterns), with our first real, attributed case study:
  a same-day-fixed 4-finding review of [mcp-gmail-manager](https://github.com/arthjhon/mcp-gmail-manager)
  (0 Critical / 0 High / 2 Medium / 2 Low), publicly linked from that project's own SECURITY.md.

## [1.0.0]

### Added
- 6-protocol any-to-any mesh: MCP, A2A, ACP, OpenAI, Gemini, AGNTCY — conformance-tested vs the real SDKs.
- Canonical hub-and-spoke translation model (no N² pairwise mappings).
- Governance plane: Ed25519 agent identities, per-agent budgets, human-in-the-loop approvals, tamper-evident hash-chained audit.
- Policy engine v2: declarative rules (cost caps, capability allow/deny, business hours, route blocking).
- RBAC for operators (admin/operator/viewer); OIDC/JWT operator SSO.
- Control-plane HTTP API (FastAPI) with OpenAPI docs; drop-in MCP server packaging; in-line proxy.
- Framework integration helpers (LangChain, CrewAI, AutoGen, LlamaIndex).
- Multi-worker concurrency safety: atomic audit-chain + budget operations on a shared store (SQLite/Postgres).
- 153 passing tests (159 with a Postgres DB).
