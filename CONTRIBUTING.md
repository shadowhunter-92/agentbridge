# Contributing to AgentBridge

Thank you for helping improve AgentBridge, an **experimental alpha** for agent-protocol interoperability and governed execution. We welcome bug reports, interoperable test cases, documentation, accessibility fixes, and narrow security improvements.

## Before you begin

- Read [README](README.md), [Security Policy](SECURITY.md), and [Code of Conduct](CODE_OF_CONDUCT.md).
- Discuss substantial changes in an issue before implementing them, so work is not duplicated.
- Never test destructive actions against a third-party system or production database without explicit authority.
- Do **not** disclose credentials, customer data, sensitive logs or exploitable vulnerabilities in a public issue. Follow `SECURITY.md`.

## Set up

Python 3.11 or 3.12 is supported for the basic local test workflow.

```bash
git clone https://github.com/shadowhunter-92/agentbridge.git
cd agentbridge
python -m venv .venv

# Activate:
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

python -m pip install -e ".[test]"
python -m pytest tests/ -q
python examples/quickstart.py
```

The PostgreSQL integration tests require an isolated disposable PostgreSQL database and the `AGENTBRIDGE_TEST_PG` environment variable; without it, those tests skip. For CI-controlled failure drills, follow the explicit scope and opt-in procedures in the draft [operator drill documentation](https://github.com/shadowhunter-92/agentbridge/blob/release/r4-internal-gates-2026-10/docs/PRODUCTION_OPERATOR_DRILLS.md). Never run recovery drills against real customer records.

## Good first contributions

1. Improve a reproducible getting-started example, including Windows support.
2. Add precise negative tests for malformed/unsupported protocol messages.
3. Document a reproducible interoperability limitation using a pinned SDK.
4. Improve validation, error messages, typing, accessibility and troubleshooting.
5. Test the **draft** Trust/Evidence SDK with synthetic state and report measured setup effort.

## Pull request checklist

- Keep one problem or feature per PR, link an issue, and explain the user benefit.
- Add tests that fail before the fix and pass afterward, when applicable.
- Specify Python/protocol SDK versions and expected behavior, including rejected cases.
- Describe security boundaries and whether your change affects identity, approvals, state transitions, budgets, receipts, logging, key management or network access.
- State what you ran locally and what needs CI or independent review.
- Update documentation and the compatibility matrix when changing behavior.
- Keep PRs small and avoid unrelated formatting or refactors.

All security-critical behavior must fail closed on invalid identity, unexpected state, untrusted evidence or unavailable authoritative data. A signed action claim alone does not establish that the external effect occurred.

## Engineering workflow

Contribute from your own fork or a narrowly scoped branch. The default `main` branch is the public prototype. Large production-hardening work remains in draft [PR #34](https://github.com/shadowhunter-92/agentbridge/pull/34); do not assume it is shipped. CI passing is necessary but not equivalent to security certification.

## Developer evaluations

Independent engineering feedback is welcome **now** for synthetic and read-only workflows. See [OSS evaluator kit](https://github.com/shadowhunter-92/agentbridge/blob/release/r4-internal-gates-2026-10/docs/OSS_EVALUATION_KIT.md). Share installation time, existing-stack comparison, error cases and reproducible evidence. Do not connect the alpha to unsupervised consequential customer actions.

Maintainers may ask for changes or decline proposals that expand unsupported protocol/security claims without end-to-end evidence.

Thank you for helping build dependable, interoperable agent infrastructure.
