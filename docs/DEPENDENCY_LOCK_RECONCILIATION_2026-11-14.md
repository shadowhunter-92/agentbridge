# Pydantic floor and runtime lock reconciliation — November 14, 2026

**PARTIALLY TESTED; production NO-GO.** Baseline:
`f309a35cb5c3ec4164acea5ba2622dc04be6807c`. The local candidate preserves
the existing PR #84 head `23e9851bc5e987eed7e2d50fbdf2491343ad75f8`
through a normal merge. It is not a rebase or history rewrite.

## Reproduced problem

PR #84 raises `pydantic` to `>=2.14.2` in the two manifests but leaves the
runtime lock at Pydantic 2.14.1 / core 2.50.1. Its historical
[CI run 41332417404](https://github.com/shadowhunter-92/agentbridge/actions/runs/41332417404)
has 22 successful jobs, a failed `package-review`, and a dependent skipped
`container-security-review`. The package review intentionally rejects the
compiled candidate's mismatch with the retained lock. Those are historical
results against the old PR/base, not this candidate's CI evidence.

The two upstream advisories are [GHSA-qpmf-fgh3-ff25](https://github.com/pydantic/pydantic/security/advisories/GHSA-qpmf-fgh3-ff25)
and [GHSA-3r8g-cqwr-jr29](https://github.com/pydantic/pydantic/security/advisories/GHSA-3r8g-cqwr-jr29).
The inspected first-party request models avoid the affected configurations;
optional SDK/deployment applicability remains under review. Package presence
and a synthetic dependency regression are not proof of an AgentBridge exploit.

## Small correction

Keep the two reviewed manifest floors and regenerate the complete runtime
hash lock with Pydantic 2.14.2 / core 2.50.2. The package set is unchanged:
all 17 other runtime packages retain exactly the same versions and hash sets.
The two changed hash sets match every published distribution on the official
PyPI release metadata: two Pydantic distributions and 141 core distributions.

Final runtime lock SHA-256:
`a7a205804c2cee8e82e8dc67908f78a667e22148107bf9526f51152a7a3745b8`.

The existing CI compile/diff guard and all workflow files are unchanged. A
Linux Python 3.12.3 / pip-tools 7.6.2 preparation selects only the two intended
versions, then recompiles using the unchanged CI command twice. The resulting
lock compares byte-for-byte equal on the final guard. Apache-2.0, NOTICE,
CODEOWNERS and all `src/` files are unchanged.

## Positive and negative evidence

Five new dependency compatibility cases cover typed JSON-extra keys,
TypedDict/dataclass alias validation, and strict tenant/task request bodies.
Before this correction, unchanged Python 3.12.10 with Pydantic 2.14.1 / core
2.50.1 produced three failures and two passes. The three failures reproduce
the upstream validation behaviors; the two first-party strict-body controls
already pass. No target or consequential action is executed by those cases.

The independent local lock verifier also accepts correct distribution sets
and rejects missing, changed or extra hashes and duplicate package entries.
Its original utility incorrectly sliced a package-name prefix as a new block
and reported empty hash sets. The failure and original script are retained;
the corrected whole-file block parser, its controls and official metadata
receipts are separate evidence. This was a verification-tool defect, not a
discovered missing release hash in the generated lock.

A new owned Windows Python 3.12.10 environment started with only pip. The
complete runtime installed with `--require-hashes`; runtime and subsequent
test/SDK `pip check` both report no broken requirements. The targeted tenant,
task-intent, atomic-admission and official-SDK compatibility cohort passed
**75 cases**, with **65 explicit PostgreSQL skips**, zero failures/errors,
in 44.72 seconds. The five new dependency cases are included in that count,
not additional tests. No source under test changed during execution.

The selected modules are `test_pydantic_dependency_compatibility.py`,
`test_tenant_http.py`, `test_task_intents_http.py`, `test_task_intents.py`,
`test_task_admission.py`, `test_protocol_negative_sdk_cases.py` and
`test_real_conformance.py`. Installed SDKs include MCP 1.30.0, A2A 0.3.26,
ACP 1.0.3, OpenAI 3.51.0, google-genai 3.3.0 and AGNTCY ACP 1.5.2.
These are the actual local package versions, not blanket protocol claims.
pytest-asyncio reports its unset fixture-loop-scope deprecation warning;
the warning is retained, not suppressed to obtain a pass.

The local receipt is retained at
`pydantic-unit-evidence-20261113/clean-qualification-20261114-attempt1/receipt.json`.
Final independent hash evidence is
`pydantic-unit-evidence-20261113/verified-public-hashes-v2-final-20261114.json`.
No hosted CI has been run for this local candidate yet; results must not be
borrowed from its base. No PostgreSQL qualification is inferred from skips.

## Remaining acceptance and rollback

After applicable publication approval, require fresh exact-head Linux
Python 3.11/3.12, Windows, SQLite, actual PostgreSQL, package and container
review results. The runtime installation is hash-required; the broader
optional test-SDK dependency closure is not claimed to be fully hash locked.
No complete repository exploitability, release provenance, independent review
or production acceptance is claimed.

Before merge, retain the original branch/main and discard only a rejected
new candidate. After a separately owner-approved merge, a normal revert is
possible; reverting the dependency correction restores an advisory-affected
package version and must be described honestly. No automatic rollback,
release, deployment, spending, branch deletion, external correspondence or
P35 change is part of this unit. Protected-main merge needs explicit approval.
