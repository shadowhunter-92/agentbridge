# OpenTelemetry API dependency floor — November 20, 2026

**Status: PARTIALLY TESTED. Local verification completed November 21; hosted checks remain pending.**

This local unit is based on `f309a35cb5c3ec4164acea5ba2622dc04be6807c`.
It adds `opentelemetry-api>=1.45.2` to the package and development manifests and
changes only the resolved API package and its dependency annotations in the
hash-locked runtime graph. All other runtime pins remain unchanged.

## Reason and scope

The [official upstream advisory](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg)
identifies CVE-2026-126360 / GHSA-mf5v-w3w3-f6cg in API versions through 1.45.1
and identifies 1.45.2 as fixed. Its affected propagator can consume excessive CPU
on a crafted `traceparent` value when an application extracts from an untrusted
carrier that permits sufficiently large strings containing embedded newlines.
The fixed release checks the 512-character limit before matching the regex.

The baseline resolves API 1.45.1 through FastAPI. Making the patched minimum an
explicit runtime dependency prevents that transitive dependency from resolving
below the fixed release when a new environment is built. The updated lock uses
the [official API 1.45.2 wheel and source distribution hashes](https://pypi.org/pypi/opentelemetry-api/1.45.2/json).

Inspection found first-party span initialization in `src/observability`, without
establishing a first-party untrusted-carrier extraction path. These checks prove
bounded upstream parser behavior and compatibility. They do not demonstrate an
AgentBridge denial-of-service exploit. No stress, external target, or configured
telemetry exporter endpoint was used.

## Local evidence

Windows checks used a fresh owned Python 3.12.10 environment. The earlier
full-optional environment was only used read-only for the old-API parser control.
Each command's exact arguments, exit status and output digest are retained in
the local evidence receipts named below.

| Check | Result | Receipt |
| --- | --- | --- |
| Runtime install into an empty environment with `pip install --require-hashes -r requirements-runtime.lock` | Passed; API 1.45.2 and all 19 locked distributions installed | `clean-hash-runtime-install.json` and install report |
| Runtime `pip check` before optional installs | Passed | `clean-runtime-pipcheck.json` |
| Final bounded parser suite against API 1.45.1 | 10 passed, 2 expected failures: 513-character rejection and refusal before regex | `baseline-old-api-final.json` / XML |
| Same final suite against API 1.45.2 | 12 passed | `fixed-api-final.json` / XML |
| Coherent optional OTEL stack and `pip check` | Passed; API/SDK/HTTP exporter 1.45.2, semantic conventions/FastAPI instrumentation 0.66b2 | `optional-sdk-pipcheck.json`, `optional-sdk-inventory.json` |
| First-party enabled span, provider, exporter and instrumentation imports | Passed; span had valid context and preserved its attribute, with no exporter endpoint | `optional-sdk-smoke.json` |
| Nearby `tests/test_production_readiness.py` | 22 passed; one Starlette TestClient deprecation warning | `readiness-regression.json` / XML |
| Linux Python 3.12.3 / pip-tools 7.6.2 compile-and-diff guard | Passed; regenerated runtime lock is byte-identical | `linux-lock-guard-attempt2.json`, `linux-lock-comparison-attempt2.json` |

The parser suite uses inputs no longer than 513 characters. It covers legitimate
trace identity and flags, absent/default extraction, supplied-context preservation
for absent or invalid carriers, bounded malformed values including an embedded
newline, a 512-character legitimate control, and two separate 513-character
guards. The original nine-case baseline (7 passed, 2 expected failures) is also
retained separately as `baseline-old-api.json`.

[Official SDK 1.45.2 metadata](https://pypi.org/pypi/opentelemetry-sdk/1.45.2/json)
requires API `==1.45.2` and semantic conventions `==0.66b2`.
[HTTP exporter 1.45.2 metadata](https://pypi.org/pypi/opentelemetry-exporter-otlp-proto-http/1.45.2/json)
requires SDK `~=1.45.2`. The fresh optional environment uses that coherent pair;
upgrading API alone in the older SDK 1.45.1 environment was avoided. A post-install
inventory confirmed all 19 runtime pins still match the lock.

The Linux check copied the manifest and seeded runtime lock into an owned
temporary directory, then ran the repository's compiler command:

```sh
python -I -m piptools compile --generate-hashes --allow-unsafe \
  --output-file candidate-runtime.lock pyproject.toml
```

Both lock files have SHA-256
`4cafc3169cb70cfd49b526cf932c70c9166ab9dfb78e639e1ed840c408c2e42b`.

For the focused checks, use an isolated environment with the hash-required
runtime graph, install the optional SDK/exporter 1.45.2 and instrumentation
0.66b2 plus the test tools, then run:

```sh
python -m pip check
python -B -m pytest tests/test_otel_dependency_compatibility.py -q -p no:cacheprovider
python -B -m pytest tests/test_production_readiness.py -q -p no:cacheprovider
```

## Limits and independent work

The baseline still pins Pydantic 2.14.1 / pydantic-core 2.50.1. The independent
Pydantic 2.14.2 fix is [PR #84](https://github.com/shadowhunter-92/agentbridge/pull/84)
at `9fcbd1ddd079527501e4df4d7cc041b076991fad`; it is not part of this unit.
A successful OTEL parser or dependency check does not establish that this baseline
has no other dependency advisories. Combined Pydantic/OTEL and hosted qualification
must be tied to their own resulting source revision.

Initial setup failures are retained: sandboxed Windows `ensurepip` could not write
its temporary wheel; a fresh elevated venv succeeded. Sandboxed WSL enumeration
was denied; scoped elevated enumeration succeeded. Ubuntu lacks `ensurepip`, so
the first Linux venv attempt failed without changing OS packages. These preparation
failures are separate from application test outcomes. The successful Linux
attempt created a fresh `--without-pip` venv and used the existing Linux pip only
to install pip 25.0.1 and pip-tools 7.6.2 into that new environment. No existing
environment was copied or upgraded. The compiler emitted its existing
`--strip-extras` future-default warning; pytest also reported an unset
`asyncio_default_fixture_loop_scope` deprecation notice.

No publication, protected-main merge, deployment, cloud or outbound workflow
change is authorized by these local results. Earlier approvals and CI receipts
apply to their earlier source heads and do not cover this new local unit.
