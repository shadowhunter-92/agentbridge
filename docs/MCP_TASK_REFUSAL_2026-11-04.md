# MCP task-augmentation refusal — November 4, 2026

**Status: PARTIALLY TESTED.** The bounded refusal unit has local test evidence;
Phase 6 protocol qualification remains incomplete.
Local qualification continued on November 5 without changing the runtime guard.

1. **Baseline / ending commit.** The isolated checkout starts at
   `35f37222597341d2c23e9cd9d0baddf1e36f99f7`. HEAD remains that commit while the
   patch is under local review. Before/after file SHA-256 pins identify the tested
   working tree; a baseline commit alone does not identify these uncommitted changes.

2. **Audited.** Canonical MCP/A2A adapters, supported-action dispatch boundary,
   inline proxy, pinned SDK requirements, protocol schema tests, the owned-task
   A2A HTTP/SSE observer and its negative/replay/authentication/deadline tests.
   No applicable `AGENTS.md` was present in the checkout or its ancestors.

3. **Already implemented.** Unsupported MCP procedures and A2A control/state
   messages refuse canonical action translation. The separate A2A observer
   authenticates existing-task ownership, rechecks credentials while streaming,
   replays bounded durable status events and refuses new execution and external
   cancellation. These components were retained. Existing MCP Streamable HTTP
   session, tool-error, bad-Origin and unknown-session tests use an official
   synthetic SDK server.

4. **Changed.** `McpAdapter.to_canonical_call` now rejects the presence of
   `params.task` before constructing an executable canonical call. The previous
   behavior silently erased task augmentation and invoked the ordinary action.
   Empty objects, null, false and malformed task values also refuse. A field named
   `task` inside tool `arguments` remains ordinary tool data. No governance,
   authority, accounting, queue or transport module was replaced.
   A separate PostgreSQL integration CI step now selects the new test module
   before the existing restore drill; all earlier test selections are preserved.

5. **Tests / results.** The initial 90 added tests first produced **80 failures,
   10 passes, zero errors** on the original adapter, then **90 passes, zero skips**
   after the guard. They cover adapter rejection, all six canonical destinations,
   inline transport refusal, library admission and signed HTTP refusal without
   budget or invocation changes. Successful ordinary calls still translate,
   dispatch through a local stub and settle exactly once. The installed official
   SDK accepts the valid `{}` and `{"ttl":60000}` task-augmented shapes. Test
   evidence is local Windows / Python 3.12.10; dependency versions are MCP SDK
   `1.30.0`, A2A SDK `0.3.26` and httpx `0.28.1`. Receipts, complete pytest logs,
   JUnit XML and source SHA-256 pins are retained outside the source checkout in
   sibling `phase6-mcp-task-refusal-evidence-20261104`. An affected regression
   group then produced **375 passes, 173 expected PostgreSQL skips, three upstream
   A2A client deprecation warnings** in 109.24 seconds with no database DSN set.
   After strengthening library refusal assertions to use a shared SQL store
   and verify no approval request is created, the final unit suite produced
   **90 passes and eight expected PostgreSQL skips** without a DSN. The initial
   RED/GREEN receipts remain separate from this expanded suite. On November 5,
   a schema-only local PostgreSQL 16 cohort produced **28 passes, zero failures
   or skips**, in 41.89 seconds: eight new refusal variants, 12 A2A HTTP/SSE status
   cases and eight direct SQL admission/crash/accounting cases. This exercises
   the expanded module's eight PostgreSQL variants omitted by the no-DSN run.
   Per-cohort counts overlap and must not be added into a unique-test total.
   The PostgreSQL host/database were fixed to the already owned loopback service;
   credentials were loaded only in memory. Its initial runner preflight failed
   before connecting because config fields were misidentified; that failed
   attempt and the corrected run are retained separately. Tenant fixtures that
   create roles or change database-wide TEMP privileges were excluded.
   Receipts are `red/receipt.json`, `green/receipt.json`,
   `affected-local/receipt.json`, `final-unit-sqlite/receipt.json` and
   `owned-pg-20261105-corrected/receipt.json`; the failed preflight is
   `owned-pg-20261105/preflight-failure.json` in the evidence directory.

6. **CI links.** New source CI: **NOT STARTED**. The baseline run
   [41638001805](https://github.com/shadowhunter-92/agentbridge/actions/runs/41638001805)
   is separate historical evidence and does not qualify this patch.
   No remote job was dispatched by this unit. Workflow selection/YAML checks and
   local Markdown target checks passed; they are local static checks, not hosted
   CI results. The added PostgreSQL step uses the job's existing disposable service.

7. **New defects.** The task-semantic erasure is addressed by refusal. Separately,
   **NOT STARTED**: `McpAdapter.to_canonical_result` and
   `A2aAdapter.to_canonical_result` parse a JSON-RPC envelope containing only
   `error` as an empty successful `CanonicalResult(is_error=False)`. Reproduction:
   pass `{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found"}}`
   to either adapter. A follow-on should define explicit error-envelope refusal
   or preservation and test `ProtocolRegistry.translate_result`; it is outside
   this request-side guard.

8. **Internal partials.** MCP durable-task creation, deferred result retrieval,
   polling, notification and cancellation are not implemented by this guard.
   The separate legacy `TranslationEngine` remains a translation-only surface;
   this unit qualifies the canonical adapter/registry, inline supported-action
   boundary, governance library and `/control/translate/call` / `/control/route`
   paths only. No full protocol certificate or SDK migration is claimed.

9. **External / owner blocks.** Full A2A 1.x or current MCP interoperability,
   external cancellation acknowledgements, independently enforced target effects,
   workload authentication and operated production transport still require
   separate qualification. AWS and paid infrastructure are outside this unit;
   no new cloud request, credential, deployment or outside message is involved.

10. **Branch / PR.** Local branch `fix/mcp-task-refusal-2026-11-04`; no PR,
    commit, publication or merge was created by this unit. The root-owned AWS
    command-evidence checkout and the isolated blocked replay-capacity candidate
    P35 were not changed.

11. **Security / release gates.** Preserve the production transport restriction,
    tenant authority, signed queued intent, private preparation, atomic accounting
    and conservative UNKNOWN handling. Task augmentation refusal does not authorize
    replay, task creation or consequential remote execution. Any release still
    requires review and exact-source CI; local tests are not CI evidence.

12. **Next tasks, in priority order.** Review this bounded guard and its receipts;
    qualify the exact final source through the approved CI process; handle the
    separate JSON-RPC result error-envelope gap; then plan versioned protocol
    lifecycle work behind the existing governance boundaries.

Official documentation was checked on **2026-11-04**:

- [MCP 2025-11-25 tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
  defines `params.task` augmentation and distinct acceptance/deferred-result
  semantics. This is the relevant revision for the pinned local MCP client.
- [MCP versioning](https://modelcontextprotocol.io/specification/versioning)
  identifies protocol revision `2026-07-28` as current. Protocol date revisions
  are separate from Python SDK major versions.
- [Official MCP Python SDK 1.30.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v1.30.0)
  identifies 1.x as the maintenance line and 2.x as the current SDK line. This
  unit retains 1.30.0; it does not claim MCP SDK 2.x compatibility.
- [A2A 0.3 specification](https://a2a-protocol.org/v0.3.0/specification/)
  and [official SDK 0.3.26 release](https://github.com/a2aproject/a2a-python/releases/tag/v0.3.26)
  identify the reviewed family used by the existing observer and tests.
- [Current A2A specification](https://a2a-protocol.org/latest/specification/)
  identifies released specification `1.0.0`, including breaking object-format
  changes. This repository's 0.3 tests do not establish A2A 1.0 compatibility.
