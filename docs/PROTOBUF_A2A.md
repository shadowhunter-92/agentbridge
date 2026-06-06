# Deferred: A2A gRPC / Protobuf Transport Support

**Status:** NOT implemented. Deliberately deferred until a real agent needs it.
**Decision (2026-06-06):** The bridge targets the **A2A JSON-RPC public spec** today,
because that is what live agents speak. This doc records exactly how to add the
protobuf transport later so we don't have to re-discover it.

## Why two formats exist

A2A ships more than one wire format. They are **not interchangeable JSON**:

| Aspect            | JSON-RPC spec (what we target now) | gRPC / Protobuf (a2a-sdk 1.x)        |
|-------------------|------------------------------------|--------------------------------------|
| Task discriminator| `"kind": "task"`                   | no `kind` field                      |
| Message list      | `history: [...]`                   | `history: [...]` (same name)         |
| Role values       | `"user"` / `"agent"` (lowercase)   | `ROLE_USER` / `ROLE_AGENT` (enums)   |
| TaskState         | `"submitted"`, `"input-required"`  | `TASK_STATE_SUBMITTED`, etc.         |
| Part text         | `{"kind":"text","text":...}`       | `{"text": ...}` (oneof, no `kind`)   |
| Part data         | `{"kind":"data","data":{...}}`     | `{"data": {...}}`                    |
| Defined by        | JSON Schema in the A2A spec        | `a2a/v1/a2a.proto` (protobuf)        |

A single JSON blob cannot satisfy both — protobuf JSON uses uppercase enums and
omits the `kind` discriminator. So protobuf support means an **explicit output
format switch**, not a tweak.

## Real protobuf schema (captured from a2a-sdk 1.1.0)

```
Task     fields: id, context_id, status, artifacts, history, metadata
Message  fields: message_id, context_id, task_id, role, parts, metadata, extensions, reference_task_ids
TaskStatus fields: state, message, timestamp
Part     fields: text, raw, url, data, metadata, filename, media_type   (oneof content)
Artifact fields: artifact_id, name, description, parts, metadata, extensions
TaskState enum: TASK_STATE_UNSPECIFIED|SUBMITTED|WORKING|COMPLETED|FAILED|CANCELED|INPUT_REQUIRED|REJECTED|AUTH_REQUIRED
Role enum: ROLE_UNSPECIFIED|ROLE_USER|ROLE_AGENT
```

The protobuf classes live in `a2a.types.a2a_pb2` and convert to/from JSON with
`google.protobuf.json_format.MessageToDict` / `ParseDict`.

## How to install (later)

```bash
# The protobuf transport ships in a2a-sdk >= 1.0 (our conformance tests pin 0.3.x
# for the JSON-RPC pydantic types — keep BOTH available in a dedicated venv to
# avoid the version clash, or test protobuf in isolation).
pip install "a2a-sdk>=1.1.0"
```

Note: a2a-sdk 0.3.x (JSON-RPC pydantic types, used by `tests/test_real_conformance.py`)
and a2a-sdk 1.x (protobuf types) cannot both be installed in the same env. Use a
separate venv for the protobuf conformance test.

## How to wire it (single change point)

All A2A Task construction is centralized in **one** method:
`src/engine/translation_engine.py :: _translate_jsonrpc_mcp()`.

Plan:
1. Add a config/param `a2a_format: "jsonrpc" | "protobuf"` to `TranslationEngine`
   (default `"jsonrpc"`), surfaced on the `/translate` request body and engine config.
2. In `_translate_jsonrpc_mcp`, branch on `self.a2a_format`:
   - `jsonrpc` → current behaviour (kind/history/lowercase roles).
   - `protobuf` → build a `a2a_pb2.Task(...)` and emit `MessageToDict(task)` (no `kind`,
     `ROLE_AGENT` enums, oneof parts).
3. Mirror the branch in the reverse path (`_translate_jsonrpc_a2a` / extraction helpers):
   accept BOTH `ROLE_AGENT`/`agent` and uppercase/lowercase task states.
4. Add `tests/test_protobuf_conformance.py` that round-trips bridge output through
   `a2a_pb2.Task` via `ParseDict(..., ignore_unknown_fields=False)` — i.e. the same
   rigor as `test_real_conformance.py` but for protobuf.

## Effort
~1–2 hours including the conformance test. No rewrite — it is additive because the
JSON-RPC construction is already isolated to one method.

## Trigger to actually build it
Build it when a real counterparty agent requires gRPC/protobuf A2A (most do not yet).
Until then this stays deferred per the "don't over-build before demand" rule.
