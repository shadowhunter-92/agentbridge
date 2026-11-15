# Preserved operational reference and probe boundaries — November 15, 2026

**PARTIALLY TESTED; production NO-GO.** Baseline:
`f309a35cb5c3ec4164acea5ba2622dc04be6807c`. This is a narrow documentation and
test follow-up; product source and runtime behavior are unchanged.

## Audited and already implemented

The five `prod/readiness-pass` commits are ancestors of maintained main.
Their current behavior was statically mapped to current source and tests.
The useful endpoint/configuration content of legacy `4db3cc1` was still
missing from the API/deployment references; its production/compliance and
blanket scaling claims remain deliberately superseded.

`src/api/control_plane.py` already provides `/health`, `/ready`, `/version`
and `/metrics`. Liveness stays HTTP 200 during drain, whereas readiness is
HTTP 503 during drain or when its store probe is unhealthy. The CLI already
passes shutdown grace in integer seconds and forces one worker during reload.

## Small correction

The references now document the exact probe shapes and optional metrics
fallback; static-key versus dynamic-JWKS setup; environment, logging, drain
and optional OTLP settings. They identify the legacy surface, preserve the
production target refusal and explain that a probe is not external execution
or physical HA acceptance. Shared-store test results no longer read as a
universal no-fork/no-double-spend deployment guarantee.

Four new negative boundary cases verify drain versus liveness, unhealthy
store versus liveness, and seconds/reload-worker handling at the intercepted
uvicorn boundary. The CLI tests start no server. The HTTP cases use fresh
owned SQLite fixtures and close them; PostgreSQL and cloud are not involved.

## Validation

- Eight selected existing positive/configuration-negative cases passed in
  4.21 seconds: endpoint shapes, metrics, structured logging, clean config,
  missing production prerequisites, configured SQLite, bad rate and bad issuer.
- Four new cases passed in 2.50 seconds. They are disjoint from those eight;
  a later joint composition run must report its own cohort rather than adding
  these counts again.
- The existing documentation checker and diff check pass. The pytest-asyncio
  unset loop-scope deprecation warning is retained rather than suppressed.

These are local Python 3.12 results. They do not simulate an actual database
outage, signal delivery, full socket draining, process kill, migration,
physical failover or production monitoring. No hosted CI for this local unit
has run yet. Existing passing main CI is not reassigned to this later unit.

## Remaining acceptance and rollback

Issue #38 remains open: the full legacy behavior/test reconciliation and
owner acceptance are separate from ancestry and this bounded probe unit.
Dynamic-route telemetry identities, operated shutdown and actual backend
failure/recovery need their own evidence. This change supplies no permission
to close the issue, change protection or delete its preserved branch.

Review and publish only under applicable owner conditions, then record exact
head CI before requesting a separate protected-main merge. Rollback is an
ordinary revert of these documentation/test files; no state or history is
deleted. Apache-2.0, NOTICE, CODEOWNERS, P35 and all production fail-closed
controls are unchanged. No release, deployment, spending or correspondence
occurred.
