# Governed MCP synthetic transfer

Experimental alpha. Synthetic tools only. Production remains NO-GO. This
demonstration moves no money and uses no Stripe account, API key, cloud or LLM.
The client is deterministic; it does not claim LangChain or model agency.

## Native: install, run, inspect

1. From the repository root, use a local virtual environment with Python 3.11+
   and the project dependencies: `python -m pip install -e . mcp==1.30.0`.
2. Run one command: `python -m examples.governed_mcp_demo --output outputs/my-demo`.
   Type `APPROVE` at the prompt. Use a fresh output directory for every run.
3. Within five minutes, verify offline:

   ```sh
   python demo/governed-mcp-demo/verify_receipt.py --bundle outputs/my-demo/evidence-bundle.json --trust outputs/my-demo/trust-roots.json --expected outputs/my-demo/expected-action.json
   ```

The installed `agentbridge-verify-evidence` command accepts those same flags.
No gateway or server is needed for verification. The existing verifier checks
signatures, exact action binding and readback freshness (300 seconds); an old
attestation correctly fails freshness. `offline-verification.json` preserves
the actual verification performed during the run. Keys and expected action are
retained by this same demo operator: this is not independent custody.

## Compose: one interactive command

From the repository root:

```sh
docker compose -f demo/governed-mcp-demo/docker-compose.yml run --build --rm demo
```

Type `APPROVE`. Use `run` so the approval prompt receives stdin. `up` does not
provide this interactive approval flow. The first build needs dependency
downloads; runtime uses `network_mode: none`, a nonroot user, a read-only image
and a retained named evidence volume. The application creates a fresh `run`
directory within that volume and refuses reuse. For another retained run, set
`DEMO_RUN` to a new name; do not delete evidence to make a test pass.

Verify promptly with:

```sh
docker compose -f demo/governed-mcp-demo/docker-compose.yml run --rm verify
```

Use the same `DEMO_RUN` for both commands. Container dependency closure is not
fully hash locked; this is a local evaluation recipe, not release provenance.
Native execution has been tested; container execution is separately reported
in the dated qualification record.

## What happens

A real official MCP 1.30.0 stdio handshake starts an owned local tool process.
The existing `GovernanceGateway` shares one durable `SqliteStore` with identity,
budget, request-bound approval, operation ledger and audit. It denies the
synthetic 1,000,000-cent ($10,000) call before dispatch. One explicit approval
permits one claim and reserves its full exposure. The MCP tool reuses
`FencedSqliteTarget`; its destination key stays in that process's memory.
Its signed receipt binds the action fingerprint, which includes the amount.
A separate `SandboxReadOnlyObserver` connection and key verify the committed
state. The existing offline verifier must accept before success accounting.

`MCP isError`, protocol errors, malformed results, failed readback and timeouts
are exceptions before gateway success settlement. The demo refuses MCP task
augmentation. Core protocol modules are unchanged; this is a bounded adapter
at this demo's invocation boundary, not blanket protocol qualification.

## Negative cases

Run with a fresh output for each:

```sh
python -m examples.governed_mcp_demo --output outputs/lost-ack --scenario lost-ack
python -m examples.governed_mcp_demo --output outputs/denied --scenario denied
python -m examples.governed_mcp_demo --output outputs/tool-error --scenario tool-error
python -m examples.governed_mcp_demo --output outputs/timeout --scenario timeout
python -m examples.governed_mcp_demo --output outputs/dual-claim --scenario split-brain
```

Type `DENY` for denial; type `APPROVE` for the other fault trials. Lost ACK means
the destination committed before its MCP tool response failed. Its signed
readback is exported, while ledger UNKNOWN and reserved exposure remain: the
demo never reconciles automatically. Tool-error/timeout also preserve UNKNOWN;
their controlled target records no effect. No absence observation is treated
as a failed settlement. Every admitted trial tries the same operation again
and verifies refusal before another dispatch. `split-brain` is the CLI label
for two concurrent admissions in one local authority, not a physical partition.

The small `attack_scenarios.py` wrapper exposes `double-spend`,
`bypass-approval` and `split-brain`. Receipt replay/signature tampering and
unsupported task shapes are covered by `tests/test_governed_mcp_demo.py`.

## Inspect

`summary.json` records observed effects, ledger state, cents spent/reserved,
actual SDK/protocol and process identity. `events.json` and
`completion-event.json` contain actual timestamps and narrative units for a
walkthrough. `audit.json`, request proof, expected action, public roots and
signed evidence are separate files. Private keys are not exported.

Approval has a 60-second stdin deadline; MCP requests have an 8-second deadline
(0.5 seconds in the explicit timeout case). The CLI watchdog is 100 seconds
including approval and SDK shutdown. No elapsed claim includes installation.

The tool trusts its local pipe owner. A user able to alter the database,
client or tool process can bypass this demonstration boundary. Separate local
keys/connections are not independent organizations or principals. This is not
Stripe-native fencing, real financial fulfillment, tenant-hostile-code
isolation, physical HA, universal exactly-once, production readiness or an
external evaluator return. Existing production and multi-tenant entry-point
refusals are preserved.
