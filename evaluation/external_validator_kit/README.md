# Independent developer evaluation kit — November 13, 2026

**PARTIALLY TESTED; engineering alpha; production NO-GO.** This kit is a later
documentation addition for executable source `f309a35cb5c3ec4164acea5ba2622dc04be6807c`,
tree `17fd9e48708ebed43971a4d0b53b9e6cf703c609`. Its own
[main CI 43371818001](https://github.com/shadowhunter-92/agentbridge/actions/runs/43371818001)
passed 16/16; the preceding five PRs each passed 24/24. Those internal results
are not an evaluation returned by an unrelated developer.

The purpose is to discover installation failures and whether a bounded
approval/lost-ACK/evidence workflow is useful alongside your existing tools.
No API keys, model account, Stripe account, cloud account or real payment is
needed. The deterministic client uses official MCP 1.30.0 over local stdio.
Prefer a disposable workstation or local VM and synthetic data.

## Docker route

Install Git, Docker with Compose, and allow the first image build to download
dependencies. From a terminal:

```sh
git clone https://github.com/shadowhunter-92/agentbridge.git && cd agentbridge && git worktree add --detach ../agentbridge-evaluator-runtime f309a35cb5c3ec4164acea5ba2622dc04be6807c
docker compose -f ../agentbridge-evaluator-runtime/demo/governed-mcp-demo/docker-compose.yml run --build --rm demo
docker compose -f ../agentbridge-evaluator-runtime/demo/governed-mcp-demo/docker-compose.yml run --rm verify
```

Type `APPROVE` in the demo prompt. Run verification within 300 seconds: the
existing freshness limit is intentional. Do not replace or disable it to make
an old bundle pass. The first command creates a detached executable worktree
at `../agentbridge-evaluator-runtime`; the original documentation checkout and all kit files
remain available. Record that documentation revision separately in your feedback.

Use `run`, which attaches approval stdin, rather than claiming `up` handles
interactive approval. The local image and named evidence volume remain on
your machine. Runtime has no network, a nonroot user, read-only filesystem,
and resource limits. A repeated run needs a fresh `DEMO_RUN`; keep prior
evidence. Do not run `down -v` to make a failing case pass.

The source-pinned baseline image recipe separately installs MCP 1.30.0 and
does not fully hash-lock that optional transitive closure. A later fix must
name its exact commit and its own evidence before you use its stronger claim.
This is not a trusted signed release.

## Native route

After the clone/worktree command above, enter the pinned runtime worktree.
Use Python 3.11 or 3.12 and a new virtual environment there:

```sh
cd ../agentbridge-evaluator-runtime
python -m venv .venv-evaluator
```

Activate it with `source .venv-evaluator/bin/activate` on macOS/Linux or
`.venv-evaluator\Scripts\Activate.ps1` in PowerShell, then:

```sh
python -m pip install -e . mcp==1.30.0
python -m examples.governed_mcp_demo --output outputs/evaluation-success
python demo/governed-mcp-demo/verify_receipt.py --bundle outputs/evaluation-success/evidence-bundle.json --trust outputs/evaluation-success/trust-roots.json --expected outputs/evaluation-success/expected-action.json
```

Type `APPROVE`. Use a new output directory and verify promptly. This editable
source installation is separate from the older unsigned, unpublished wheel
in the [historical OSS kit](../../docs/OSS_EVALUATION_KIT.md).

## What to test

Follow the [checklist](checklist.md), preserve failed attempts, and fill the
[feedback form](feedback.md). Review the
[security scope](security_scope.md) before any broader testing.
Do not grant this demo access to production targets or private data.

Inspect `summary.json`, `audit.json`, `events.json`, the expected action,
public trust roots, signed bundle and `offline-verification.json`.
Destination private keys are not exported. The local operator controls both
keys, the client and database: independent verification of those statements
is not separate administration or proof of financial/physical fulfillment.

The setup goal is a verified receipt in under 10 minutes **after prerequisites
are available**. No independent timing has been accepted yet. Record clone,
build/install, approval and verification separately; include first-build
downloads and failures rather than reporting only warm execution time.

## Return evidence

Do not post secrets, databases, personal documents or confidential logs.
Share a completed feedback form and redacted synthetic outputs only through
an agreed route; obtain permission before attribution. A sent invitation,
automated reply or successful internal run is not an external evaluation.
Three unrelated, completed reports remain the acceptance target.

Apache-2.0 rights are unchanged. See [LICENSE](../../LICENSE),
[SECURITY.md](../../SECURITY.md), the
[demo limitations](../../demo/governed-mcp-demo/README.md) and
[current status](../../docs/CURRENT_ALPHA_STATUS.md).
