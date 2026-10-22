"""Exact, bounded contract for the supervised queued SQLite demonstration.

This descriptor is operator configuration, never a caller-selected executable.
The only effect is persisting the exact canonical ``write(value)`` demonstration
action at one dedicated destination. It does not execute arbitrary MCP tools.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

QUEUED_DESTINATION_KIND = "queued_fenced_sqlite_v2"
DEMO_ACTION_SCHEMA = "agentbridge.demo.append.v1"
MAX_ACTION_BYTES = 4096
MAX_VALUE_BYTES = 1024
MAX_AUTHORIZATION_BYTES = 8192
MAX_RECEIPT_BYTES = 16384
MAX_READBACK_BYTES = 16384
MAX_RESULT_BYTES = 512
# Includes the authorization and all evidence, even at native Unicode ID bounds.
QUEUED_RESULT_ENVELOPE_LIMIT_BYTES = 65536

_DESCRIPTOR_FIELDS = frozenset({
    "kind", "protocol", "tenant_id", "target_id", "destination_id", "path", "action_schema",
    "authorizer_key_id", "authorizer_public_key_hex", "destination_key_id", "destination_public_key_hex",
    "observer_key_id", "observer_public_key_hex", "call_timeout_seconds", "max_action_bytes",
})


def canonical_queued_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def queued_identifier(value) -> bool:
    if (not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value
            or not value.strip() or value.strip() != value):
        return False
    try:
        return len(value.encode("utf-8")) <= 512
    except UnicodeError:
        return False


def queued_hex(value, size=64) -> bool:
    return isinstance(value, str) and len(value) == size and all(c in "0123456789abcdef" for c in value)


def queued_seconds(value) -> bool:
    return type(value) in (int, float) and 0 < value <= 253402300800 and math.isfinite(value)


def normalize_queued_descriptor(descriptor) -> dict:
    """Validate every accepted field and return independent canonical values."""
    if not isinstance(descriptor, dict) or set(descriptor) != _DESCRIPTOR_FIELDS:
        raise ValueError("exact queued destination descriptor required")
    if (descriptor["kind"] != QUEUED_DESTINATION_KIND or descriptor["protocol"] != "mcp"
            or descriptor["action_schema"] != DEMO_ACTION_SCHEMA
            or type(descriptor["max_action_bytes"]) is not int or descriptor["max_action_bytes"] != MAX_ACTION_BYTES):
        raise ValueError("unsupported queued demonstration contract")
    for name in ("tenant_id", "target_id", "destination_id", "authorizer_key_id", "destination_key_id", "observer_key_id"):
        if not queued_identifier(descriptor[name]):
            raise ValueError("bounded queued destination identity required")
    key_names = ("authorizer_public_key_hex", "destination_public_key_hex", "observer_public_key_hex")
    if any(not queued_hex(descriptor[name]) for name in key_names):
        raise ValueError("canonical 32-byte Ed25519 trust roots required")
    if len({descriptor[name] for name in key_names}) != 3:
        raise ValueError("authorization, destination and observer trust roots must be distinct")
    if len({descriptor[name] for name in ("authorizer_key_id", "destination_key_id", "observer_key_id")}) != 3:
        raise ValueError("signing key identities must be distinct")
    timeout = descriptor["call_timeout_seconds"]
    if type(timeout) not in (int, float) or not 0 < timeout <= 10 or not math.isfinite(timeout):
        raise ValueError("queued destination timeout must be finite and at most ten seconds")
    path = descriptor["path"]
    if (not isinstance(path, str) or not path or len(path) > 1024 or "\x00" in path
            or path == ":memory:" or path.startswith(("file:", "\\\\", "//")) or not Path(path).is_absolute()):
        raise ValueError("dedicated absolute SQLite destination path required")
    try:
        normalized_path = str(Path(path).resolve())
        if len(normalized_path.encode("utf-8")) > 4096 or len(normalized_path) > 1024:
            raise ValueError("destination path exceeds bounds")
    except (OSError, UnicodeError, RuntimeError) as exc:
        raise ValueError("invalid destination path") from exc
    result = dict(descriptor)
    result["path"] = normalized_path
    # Keep integer descriptors and their established target hash stable.
    result["call_timeout_seconds"] = timeout
    if len(canonical_queued_json(result)) > 8192:
        raise ValueError("normalized queued descriptor exceeds byte limit")
    return result


def queued_descriptor_sha256(descriptor) -> str:
    return hashlib.sha256(canonical_queued_json(normalize_queued_descriptor(descriptor))).hexdigest()


def canonical_demo_action(wire) -> bytes:
    """The entire accepted MCP wire, with no unchecked parameters or metadata."""
    if not isinstance(wire, dict) or set(wire) != {"method", "params"} or wire["method"] != "tools/call":
        raise ValueError("exact queued MCP tools/call required")
    params = wire["params"]
    if not isinstance(params, dict) or set(params) != {"name", "arguments"} or params["name"] != "write":
        raise ValueError("only the bounded demonstration write tool is supported")
    arguments = params["arguments"]
    if not isinstance(arguments, dict) or set(arguments) != {"value"} or not isinstance(arguments["value"], str):
        raise ValueError("one demonstration string value required")
    try:
        if len(arguments["value"].encode("utf-8")) > MAX_VALUE_BYTES:
            raise ValueError("demonstration value exceeds UTF-8 byte limit")
        raw = canonical_queued_json(wire)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("valid bounded demonstration Unicode required") from exc
    if len(raw) > MAX_ACTION_BYTES:
        raise ValueError("demonstration action exceeds canonical byte limit")
    return raw


def parse_demo_action(action_bytes) -> dict:
    if not isinstance(action_bytes, bytes) or not 1 <= len(action_bytes) <= MAX_ACTION_BYTES:
        raise ValueError("bounded canonical action bytes required")
    try:
        wire = json.loads(action_bytes)
        if canonical_demo_action(wire) != action_bytes:
            raise ValueError("action is not its exact canonical encoding")
    except (UnicodeError, RecursionError, TypeError) as exc:
        raise ValueError("invalid demonstration action bytes") from exc
    return wire


def queued_effect_id(authorization_sha256) -> str:
    if not queued_hex(authorization_sha256):
        raise ValueError("exact queued authorization digest required")
    return "sqlite-queued-effect-v2:" + authorization_sha256


def demo_result(action_bytes, authorization_sha256) -> dict:
    wire = parse_demo_action(action_bytes)
    raw_value = wire["params"]["arguments"]["value"].encode("utf-8")
    return {"domain": "agentbridge.demo-result.v1", "stored_sha256": hashlib.sha256(raw_value).hexdigest(),
            "stored_bytes": len(raw_value), "effect_id": queued_effect_id(authorization_sha256)}


def queued_result_envelope_bytes(*, authorization, result, destination_receipt, readback_attestation) -> bytes:
    """One exact storage encoding; callers retain their immutable result limit."""
    return canonical_queued_json({"authorization": authorization, "result": result,
                                  "destination_receipt": destination_receipt,
                                  "readback_attestation": readback_attestation})
