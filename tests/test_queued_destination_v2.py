"""Exact v2 demonstration effects, fenced expiry and independent readback."""
import hashlib
import json
import queue
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import FrozenInstanceError

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.destination_receipts import (
    UntrustedReceipt,
    canonical_queued_authorization_payload,
    canonical_queued_receipt_payload,
    queued_authorization_sha256,
    verify_destination_receipt,
    verify_queued_authorization,
    verify_queued_destination_receipt,
)
from src.governance.fenced_sqlite_destination import (
    _QUEUED_TRIGGER_SQL,
    FencedSqliteTarget,
    SqliteDuplicateEffect,
    SqliteFenceDenied,
)
from src.governance.queued_destination_contract import (
    QUEUED_RESULT_ENVELOPE_LIMIT_BYTES,
    canonical_demo_action,
    canonical_queued_json,
    demo_result,
    normalize_queued_descriptor,
    parse_demo_action,
    queued_descriptor_sha256,
    queued_result_envelope_bytes,
)
from src.governance.readback_attestations import (
    UntrustedReadback,
    canonical_queued_readback_payload,
    verify_queued_readback_attestation,
)
from src.governance.sandbox_readback import ObservationUnavailable, SandboxReadOnlyObserver, SandboxTarget
from src.governance.trust_sdk import verify_journaled_queued_action_evidence, verify_queued_action_evidence


def _public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


@pytest.fixture
def harness(tmp_path):
    keys = {name: Ed25519PrivateKey.generate() for name in ("authorizer", "destination", "observer")}
    descriptor = {
        "kind": "queued_fenced_sqlite_v2", "protocol": "mcp", "tenant_id": "tenant", "target_id": "demo",
        "destination_id": "destination", "path": str(tmp_path / "queued.sqlite"),
        "action_schema": "agentbridge.demo.append.v1", "max_action_bytes": 4096, "call_timeout_seconds": 10,
        **{name + "_key_id": name + "-key" for name in keys},
        **{name + "_public_key_hex": _public(key) for name, key in keys.items()},
    }
    return {"keys": keys, "descriptor": normalize_queued_descriptor(descriptor), "clock": [1790000000.25]}


def _target(harness, **kwargs):
    target = FencedSqliteTarget(harness["descriptor"]["path"], sign=harness["keys"]["destination"].sign,
                                queued_descriptor=harness["descriptor"], **kwargs)
    target.db.create_function("julianday", 1, lambda _: harness["clock"][0] / 86400 + 2440587.5)
    return target


def _action(value="bounded demo value"):
    return canonical_demo_action({"method": "tools/call", "params": {"name": "write", "arguments": {"value": value}}})


def _sign_auth(harness, authorization):
    result = dict(authorization)
    result["signature_hex"] = harness["keys"]["authorizer"].sign(canonical_queued_authorization_payload(result)).hex()
    return result


def _authorization(harness, target, *, action=None, **changes):
    action = _action() if action is None else action
    descriptor = harness["descriptor"]
    epoch = target.acquire(scope="scope", owner="worker", ttl_seconds=10)
    authorization = {
        "domain": "agentbridge.queued-authorization.v2", "tenant_id": descriptor["tenant_id"], "store_id": "store",
        "owner_id": "owner", "agent_id": "agent", "authority_sha256": "a" * 64, "task_id": "task", "context_id": "context",
        "intent_sha256": "b" * 64, "admission_link_sha256": "c" * 64, "fingerprint": "d" * 64,
        "original_action_sha256": "e" * 64, "target_id": descriptor["target_id"],
        "target_configuration_sha256": queued_descriptor_sha256(descriptor), "destination_id": descriptor["destination_id"],
        "operation_id": "operation-1234567890", "action_sha256": hashlib.sha256(action).hexdigest(),
        "result_limit_bytes": QUEUED_RESULT_ENVELOPE_LIMIT_BYTES, "attempt_id": "attempt", "fence_scope": "scope",
        "fence_owner": "worker", "fence_epoch": epoch, "issued_at": harness["clock"][0] - 0.1,
        "expires_at": harness["clock"][0] + 5, "authorizer_key_id": descriptor["authorizer_key_id"],
    }
    authorization.update(changes)
    return _sign_auth(harness, authorization)


def _count(target):
    return target.db.execute("SELECT count(*) FROM ab_queued_effects_v2").fetchone()[0]


def _observe(harness, authorization, action):
    with SandboxReadOnlyObserver(
        harness["descriptor"]["path"], destination_public_key_hex=_public(harness["keys"]["destination"]),
        sign=harness["keys"]["observer"].sign,
    ) as observer:
        return observer.observe_queued(authorization, action, harness["descriptor"])


def _verify(harness, authorization, action, result, receipt, proof, **kwargs):
    return verify_queued_action_evidence(
        authorization=authorization, action_bytes=action, descriptor=harness["descriptor"], result=result,
        destination_receipt=receipt, readback_attestation=proof, **kwargs)


def test_exact_effect_lost_ack_independent_readonly_and_no_replay(harness):
    action = _action("\U0001f33f" * 256)
    with _target(harness) as target:
        authorization = _authorization(harness, target, action=action)
        with pytest.raises(TimeoutError, match="acknowledgement dropped"):
            target.commit_queued(authorization, action, lose_ack=True)
        assert _count(target) == 1
        with pytest.raises(SqliteDuplicateEffect):
            target.commit_queued(authorization, action)
        row = target.db.execute("SELECT * FROM ab_queued_effects_v2").fetchone()
        assert row["action_bytes"] == action
        assert json.loads(row["authorization_json"]) == authorization
        assert row["authorization_sha256"] == queued_authorization_sha256(authorization)
        assert "sandbox_effects" not in {item[0] for item in target.db.execute("SELECT name FROM sqlite_master")}
        with SandboxReadOnlyObserver(
            harness["descriptor"]["path"], destination_public_key_hex=_public(harness["keys"]["destination"]),
            sign=harness["keys"]["observer"].sign,
        ) as observer:
            assert observer._db is not target.db
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                observer._db.execute("CREATE TABLE forbidden(value)")
            result, receipt, proof = observer.observe_queued(authorization, action, harness["descriptor"])
        assert result["stored_bytes"] == 1024
        assert result["stored_sha256"] == hashlib.sha256(("\U0001f33f" * 256).encode()).hexdigest()
        assert result == demo_result(action, queued_authorization_sha256(authorization))
        verified = _verify(harness, authorization, action, result, receipt, proof)
        assert verified.outcome == "succeeded"
        assert verified.authorization_sha256 == row["authorization_sha256"]
        assert verified.result_sha256 == row["result_sha256"]
        with pytest.raises(FrozenInstanceError):
            verified.outcome = "failed"
        assert len(queued_result_envelope_bytes(
            authorization=authorization, result=result, destination_receipt=receipt,
            readback_attestation=proof)) < QUEUED_RESULT_ENVELOPE_LIMIT_BYTES


def test_historical_effect_stays_verifiable_after_execution_expiry(harness):
    with _target(harness) as target:
        action = _action()
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, action)
        harness["clock"][0] += 20
        with pytest.raises(UntrustedReceipt, match="expired"):
            target.commit_queued(authorization, action)
        result, receipt, proof = _observe(harness, authorization, action)
        assert _verify(harness, authorization, action, result, receipt, proof).outcome == "succeeded"
        assert _count(target) == 1


@pytest.mark.parametrize("field", [
    "domain", "tenant_id", "store_id", "owner_id", "agent_id", "authority_sha256", "task_id", "context_id",
    "intent_sha256", "admission_link_sha256", "fingerprint", "original_action_sha256", "target_id",
    "target_configuration_sha256", "destination_id", "operation_id", "action_sha256", "result_limit_bytes",
    "attempt_id", "fence_scope", "fence_owner", "fence_epoch", "issued_at", "expires_at", "authorizer_key_id", "signature_hex",
])
def test_every_authorization_field_is_signed_and_rejects_mutation(harness, field):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        value = authorization[field]
        authorization[field] = value + 1 if type(value) in (int, float) else ("0" if value[0] != "0" else "1") + value[1:]
        with pytest.raises((UntrustedReceipt, ValueError)):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


@pytest.mark.parametrize("changes", [
    {"tenant_id": "other"}, {"target_id": "other"}, {"destination_id": "other"},
    {"target_configuration_sha256": "0" * 64}, {"authorizer_key_id": "other"}, {"action_sha256": "0" * 64},
    {"fence_epoch": True}, {"fence_epoch": 0}, {"result_limit_bytes": True}, {"result_limit_bytes": 0},
    {"result_limit_bytes": 1048577}, {"issued_at": float("nan")}, {"expires_at": float("inf")},
    {"task_id": "\ud800"}, {"operation_id": "a" * 129}, {"fingerprint": "A" * 64},
])
def test_resigned_malformed_or_wrong_destination_authorization_has_no_effect(harness, changes):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        authorization.update(changes)
        # Nonfinite values cannot be encoded by the signing contract at all.
        try:
            authorization = _sign_auth(harness, authorization)
        except ValueError:
            pass
        with pytest.raises((UntrustedReceipt, ValueError)):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


@pytest.mark.parametrize("changes", [
    {"fence_epoch": 2}, {"fence_owner": "other"}, {"fence_scope": "other"},
])
def test_valid_signature_needs_exact_authoritative_fence(harness, changes):
    with _target(harness) as target:
        authorization = _authorization(harness, target, **changes)
        with pytest.raises(SqliteFenceDenied):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


@pytest.mark.parametrize("window", [(-2, -1), (1, 2), (0, 11), (0, 0), (2, 1)])
def test_destination_clock_enforces_signed_window(harness, window):
    with _target(harness) as target:
        now = harness["clock"][0]
        authorization = _authorization(harness, target, issued_at=now + window[0], expires_at=now + window[1])
        with pytest.raises(UntrustedReceipt):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


@pytest.mark.parametrize("limit", [1, 65535])
def test_too_small_original_result_allowance_refuses_effect(harness, limit):
    with _target(harness) as target:
        authorization = _authorization(harness, target, result_limit_bytes=limit)
        with pytest.raises(ValueError, match="result allowance"):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


@pytest.mark.parametrize("wire", [
    {}, {"method": "tools/call", "params": {}, "extra": 1},
    {"method": "other", "params": {"name": "write", "arguments": {"value": "x"}}},
    {"method": "tools/call", "params": {"name": "read", "arguments": {"value": "x"}}},
    {"method": "tools/call", "params": {"name": "write", "arguments": {"value": 1}}},
    {"method": "tools/call", "params": {"name": "write", "arguments": {"value": "x", "sql": "DELETE"}}},
    {"method": "tools/call", "params": {"name": "write", "arguments": {"value": "x" * 1025}}},
    {"method": "tools/call", "params": {"name": "write", "arguments": {"value": "\U0001f33f" * 257}}},
    {"method": "tools/call", "params": {"name": "write", "arguments": {"value": "\ud800"}}},
])
def test_only_exact_utf8_bounded_demo_action_is_accepted(wire):
    with pytest.raises(ValueError):
        canonical_demo_action(wire)


@pytest.mark.parametrize("raw", [b"{}", b"[1]", b"\xff", b" " * 4097,
                                      b'{"method":"tools/call","params":{"name":"write","arguments":{"value":"x"}}}',
                                      b'{"method":"tools/call","params":{"name":"write","arguments":{"value":"x","value":"y"}}}'])
def test_only_exact_canonical_action_encoding_is_accepted(raw):
    with pytest.raises(ValueError):
        parse_demo_action(raw)


def test_action_digest_cannot_validate_one_value_and_persist_another(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        with pytest.raises(UntrustedReceipt, match="action"):
            target.commit_queued(authorization, _action("different"))
        assert _count(target) == 0


def test_native_maximum_unicode_task_context_and_operation_ids(harness):
    with _target(harness) as target:
        native = "\U0001f33f" * 128
        authorization = _authorization(harness, target, task_id=native, context_id=native, operation_id=native)
        assert len(canonical_queued_json(authorization)) < 8192
        target.commit_queued(authorization, _action())
        result, receipt, proof = _observe(harness, authorization, _action())
        verified = _verify(harness, authorization, _action(), result, receipt, proof)
        assert verified.task_id == verified.context_id == verified.operation_id == native


def test_execution_rechecks_clock_after_real_sqlite_lock_wait(harness):
    with _target(harness) as setup:
        authorization = _authorization(harness, setup)
    ready, calling = threading.Event(), threading.Event()
    messages = queue.Queue()

    # Construct worker before holding its constructor's required schema lock.
    # A separate gate puts its effect BEGIN IMMEDIATE behind a real writer.
    gate = threading.Event()
    def gated_worker():
        try:
            with _target(harness) as target:
                target.db.set_trace_callback(lambda sql: calling.set() if sql == "BEGIN IMMEDIATE" else None)
                ready.set()
                assert gate.wait(5)
                target.commit_queued(authorization, _action())
        except BaseException as exc:
            messages.put(exc)
    thread = threading.Thread(target=gated_worker)
    thread.start()
    assert ready.wait(5)
    with sqlite3.connect(harness["descriptor"]["path"], isolation_level=None) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        gate.set()
        assert calling.wait(5)
        assert thread.is_alive()
        harness["clock"][0] = authorization["expires_at"] + 0.01
        blocker.execute("COMMIT")
    thread.join(5)
    assert not thread.is_alive()
    error = messages.get_nowait()
    assert isinstance(error, UntrustedReceipt), repr(error)
    with _target(harness) as target:
        assert _count(target) == 0


def test_missing_readback_never_signs_a_failed_outcome(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        calls = []
        with SandboxReadOnlyObserver(
            harness["descriptor"]["path"], destination_public_key_hex=_public(harness["keys"]["destination"]),
            sign=lambda raw: calls.append(raw),
        ) as observer:
            with pytest.raises(ObservationUnavailable, match="unknown"):
                observer.observe_queued(authorization, _action(), harness["descriptor"])
        assert calls == []


@pytest.mark.parametrize("column,expression", [
    ("fingerprint", "'" + "0" * 64 + "'"), ("authorization_sha256", "'" + "0" * 64 + "'"),
    ("action_bytes", "X'7b7d'"), ("result_sha256", "'" + "0" * 64 + "'"),
    ("receipt_sha256", "'" + "0" * 64 + "'"), ("result_json", "'{}'"), ("receipt_json", "'{}'"),
    ("authorization_json", "'{}'"), ("committed_at", "1790000099"), ("fence_epoch", "99"),
])
def test_observer_rejects_tampered_committed_record_without_signing(harness, column, expression):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        name = "ab_queued_effects_v2_deny_update"
        target.db.execute("DROP TRIGGER " + name)
        target.db.execute("UPDATE ab_queued_effects_v2 SET " + column + "=" + expression)
        target.db.execute(_QUEUED_TRIGGER_SQL[name])
        calls = []
        with SandboxReadOnlyObserver(
            harness["descriptor"]["path"], destination_public_key_hex=_public(harness["keys"]["destination"]),
            sign=lambda raw: calls.append(raw),
        ) as observer:
            with pytest.raises(ObservationUnavailable):
                observer.observe_queued(authorization, _action(), harness["descriptor"])
        assert calls == []


@pytest.mark.parametrize("component", ["result", "receipt", "proof"])
def test_unsigned_metadata_is_never_accepted(harness, component):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        result, receipt, proof = _observe(harness, authorization, _action())
        {"result": result, "receipt": receipt, "proof": proof}[component]["extra"] = "unsigned"
        with pytest.raises(ValueError):
            _verify(harness, authorization, _action(), result, receipt, proof)


@pytest.mark.parametrize("field", ["authorization_sha256", "fingerprint", "attempt_id", "fence_epoch", "tenant_id",
                                     "operation_id", "target_id", "destination_id", "result_sha256", "committed_at"])
def test_even_resigned_receipts_must_bind_exact_authorization_and_result(harness, field):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        result, receipt = target.commit_queued(authorization, _action())
        value = receipt[field]
        receipt[field] = value + 100 if type(value) in (int, float) else "0" * len(value)
        receipt["signature_hex"] = harness["keys"]["destination"].sign(canonical_queued_receipt_payload(receipt)).hex()
        with pytest.raises(UntrustedReceipt):
            verify_queued_destination_receipt(receipt, authorization=authorization, action_bytes=_action(),
                                              descriptor=harness["descriptor"], result=result)


@pytest.mark.parametrize("offset", [-301, 31])
def test_independent_readback_must_still_be_fresh(harness, offset):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        result, receipt, proof = _observe(harness, authorization, _action())
        now = int(time.time())
        proof["observed_at"] = now + offset
        proof["signature_hex"] = harness["keys"]["observer"].sign(canonical_queued_readback_payload(proof)).hex()
        with pytest.raises(UntrustedReadback, match="stale"):
            _verify(harness, authorization, _action(), result, receipt, proof, now=now)


def test_observer_wrong_signing_key_cannot_manufacture_proof(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        with SandboxReadOnlyObserver(
            harness["descriptor"]["path"], destination_public_key_hex=_public(harness["keys"]["destination"]),
            sign=harness["keys"]["destination"].sign,
        ) as observer:
            with pytest.raises(ObservationUnavailable):
                observer.observe_queued(authorization, _action(), harness["descriptor"])


@pytest.mark.parametrize("pair", [("authorizer", "destination"), ("authorizer", "observer"), ("destination", "observer")])
def test_all_three_trust_roots_are_distinct(harness, pair):
    descriptor = dict(harness["descriptor"])
    descriptor[pair[0] + "_public_key_hex"] = descriptor[pair[1] + "_public_key_hex"]
    with pytest.raises(ValueError, match="distinct"):
        normalize_queued_descriptor(descriptor)


@pytest.mark.parametrize("change", [
    {"extra": True}, {"kind": "queued_fenced_sqlite_v3"}, {"protocol": "a2a"}, {"action_schema": "arbitrary"},
    {"path": ":memory:"}, {"path": "relative.sqlite"}, {"max_action_bytes": 4097}, {"max_action_bytes": True},
    {"call_timeout_seconds": 11}, {"call_timeout_seconds": float("nan")}, {"call_timeout_seconds": True},
    {"observer_public_key_hex": "A" * 64}, {"destination_id": ""},
])
def test_descriptor_is_strict_bounded_and_operator_specific(harness, change):
    with pytest.raises(ValueError):
        normalize_queued_descriptor({**harness["descriptor"], **change})


def test_dedicated_file_binding_and_v1_contract_are_immutable(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        with pytest.raises(ValueError, match="v1 commit"):
            target.commit(scope="scope", owner="worker", epoch=1, agent_id="agent", operation_id="operation", fingerprint="fp")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            target.db.execute("UPDATE ab_queued_destination_binding_v2 SET version=3")
        target.commit_queued(authorization, _action())
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            target.db.execute("DELETE FROM ab_queued_effects_v2")
    with pytest.raises(ValueError, match="v1 target"):
        FencedSqliteTarget(harness["descriptor"]["path"], sign=harness["keys"]["destination"].sign)
    descriptor = {**harness["descriptor"], "tenant_id": "other"}
    with pytest.raises(ValueError, match="binding"):
        FencedSqliteTarget(descriptor["path"], sign=harness["keys"]["destination"].sign, queued_descriptor=descriptor)


def test_v2_refuses_a_v1_file_instead_of_upgrading_its_namespace(harness):
    path = harness["descriptor"]["path"]
    with FencedSqliteTarget(path, sign=harness["keys"]["destination"].sign) as target:
        with pytest.raises(ValueError, match="queued-only"):
            target.commit_queued({}, _action())
    with pytest.raises(ValueError, match="schema"):
        _target(harness)


@pytest.mark.parametrize("mutation", [
    "DROP TRIGGER ab_queued_effects_v2_deny_update",
    "DROP TABLE ab_queued_effects_v2",
    "CREATE UNIQUE INDEX extra_unique ON ab_queued_effects_v2(fingerprint)",
    "CREATE TABLE unexpected(x)",
])
def test_partial_or_extra_schema_is_not_adopted(harness, mutation):
    with _target(harness) as target:
        target.db.execute(mutation)
    with pytest.raises(ValueError, match="schema"):
        _target(harness)


def test_v1_receipt_verifier_still_rejects_all_v2_metadata(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        _, receipt = target.commit_queued(authorization, _action())
        with pytest.raises(UntrustedReceipt, match="fields"):
            verify_destination_receipt(receipt, agent_id="agent", operation_id=authorization["operation_id"],
                                       fingerprint=authorization["fingerprint"],
                                       trusted_public_key_hex=_public(harness["keys"]["destination"]))


def test_authorization_exact_fields_and_total_byte_bound(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        for malformed in ({**authorization, "extra": True}, {k: v for k, v in authorization.items() if k != "owner_id"}):
            with pytest.raises(UntrustedReceipt, match="fields"):
                target.commit_queued(malformed, _action())
        oversized = dict(authorization)
        for field in ("task_id", "context_id", "operation_id", "owner_id", "agent_id", "store_id"):
            oversized[field] = "\U0001f33f" * 128
        oversized = _sign_auth(harness, oversized)
        with pytest.raises(UntrustedReceipt, match="byte limit"):
            target.commit_queued(oversized, _action())
        assert _count(target) == 0


def test_wrong_destination_signer_rolls_back_effect(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.sign = harness["keys"]["observer"].sign
        with pytest.raises(UntrustedReceipt, match="signature"):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


@pytest.mark.parametrize("key", ["tenant_id", "target_id", "destination_id", "observer_key_id", "authorizer_key_id"])
def test_descriptor_changes_cannot_rebind_an_existing_file(harness, key):
    with _target(harness):
        pass
    descriptor = {**harness["descriptor"], key: "changed"}
    with pytest.raises(ValueError, match="binding"):
        FencedSqliteTarget(descriptor["path"], sign=harness["keys"]["destination"].sign, queued_descriptor=descriptor)


def test_authorization_may_not_outlive_destination_lease(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.db.execute("UPDATE ab_destination_fences SET expires_seconds=?", (harness["clock"][0] + 1,))
        with pytest.raises(SqliteFenceDenied):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


def test_destination_epoch_change_fences_old_signed_authorization(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.db.execute("UPDATE ab_destination_fences SET expires_seconds=?", (harness["clock"][0] - 1,))
        assert target.acquire(scope="scope", owner="promoted", ttl_seconds=10) > authorization["fence_epoch"]
        with pytest.raises(SqliteFenceDenied):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


def test_expiry_boundary_is_exclusive(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        harness["clock"][0] = authorization["expires_at"]
        with pytest.raises(UntrustedReceipt):
            target.commit_queued(authorization, _action())
        assert _count(target) == 0


@pytest.mark.parametrize("kind", ["action", "authorization", "result", "receipt"])
def test_oversized_persisted_readback_is_rejected_before_payload_fetch(harness, kind):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        name = "ab_queued_effects_v2_deny_update"
        column, size = {"action": ("action_bytes", 4097), "authorization": ("authorization_json", 8193),
                        "result": ("result_json", 513), "receipt": ("receipt_json", 16385)}[kind]
        target.db.execute("DROP TRIGGER " + name)
        target.db.execute("PRAGMA ignore_check_constraints=ON")
        target.db.execute("UPDATE ab_queued_effects_v2 SET " + column + "=?", (b"x" * size if kind == "action" else "x" * size,))
        target.db.execute("PRAGMA ignore_check_constraints=OFF")
        target.db.execute(_QUEUED_TRIGGER_SQL[name])
        calls = []
        statements = []
        with SandboxReadOnlyObserver(
            harness["descriptor"]["path"], destination_public_key_hex=_public(harness["keys"]["destination"]),
            sign=lambda raw: calls.append(raw),
        ) as observer:
            observer._db.set_trace_callback(statements.append)
            with pytest.raises(ObservationUnavailable, match="exceeds bounds"):
                observer.observe_queued(authorization, _action(), harness["descriptor"])
        assert calls == []
        assert not any(sql.startswith("SELECT * FROM main.ab_queued_effects_v2") for sql in statements)


def test_oversized_binding_is_rejected_before_payload_fetch(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        name = "ab_queued_destination_binding_v2_deny_update"
        target.db.execute("DROP TRIGGER " + name)
        target.db.execute("PRAGMA ignore_check_constraints=ON")
        target.db.execute("UPDATE ab_queued_destination_binding_v2 SET descriptor_json=?", ("x" * 8193,))
        target.db.execute("PRAGMA ignore_check_constraints=OFF")
        target.db.execute(_QUEUED_TRIGGER_SQL[name])
        with pytest.raises(ObservationUnavailable):
            _observe(harness, authorization, _action())


@pytest.mark.parametrize("field", ["authorization_sha256", "attempt_id", "fence_epoch", "source_evidence_sha256",
                                     "destination_receipt_sha256", "source", "observer_key_id", "result_sha256"])
def test_even_resigned_observation_must_match_exact_committed_values(harness, field):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        result, receipt, proof = _observe(harness, authorization, _action())
        value = proof[field]
        proof[field] = value + 1 if type(value) is int else "0" * len(value)
        proof["signature_hex"] = harness["keys"]["observer"].sign(canonical_queued_readback_payload(proof)).hex()
        with pytest.raises(UntrustedReadback):
            verify_queued_readback_attestation(
                proof, authorization=authorization, action_bytes=_action(), descriptor=harness["descriptor"],
                result=result, destination_receipt=receipt)


@pytest.mark.parametrize("field,value", [("stored_bytes", True), ("stored_sha256", "0" * 64),
                                       ("effect_id", "sqlite-queued-effect-v2:" + "0" * 64),
                                       ("domain", "agentbridge.demo-result.v2")])
def test_result_must_be_the_exact_effect_derived_from_actual_action(harness, field, value):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        action = _action("x")
        authorization["action_sha256"] = hashlib.sha256(action).hexdigest()
        authorization = _sign_auth(harness, authorization)
        result, receipt = target.commit_queued(authorization, action)
        result[field] = value
        with pytest.raises(UntrustedReceipt):
            verify_queued_destination_receipt(receipt, authorization=authorization, action_bytes=action,
                                              descriptor=harness["descriptor"], result=result)


def test_duplicate_operation_and_attempt_keys_are_not_result_replay(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        for changes in ({"attempt_id": "new-attempt"}, {"operation_id": "other-operation-1234567890"}):
            second = _sign_auth(harness, {**authorization, **changes})
            with pytest.raises(SqliteDuplicateEffect):
                target.commit_queued(second, _action())
        assert _count(target) == 1


def test_v1_sandbox_writer_also_refuses_queued_only_file(harness):
    with _target(harness):
        with pytest.raises(ValueError, match="v1 sandbox"):
            SandboxTarget(harness["descriptor"]["path"], sign=harness["keys"]["destination"].sign)


def test_journal_wrapper_reuses_current_pins_and_rejects_revocation(harness, tmp_path):
    from src.governance.signing_trust_journal import (
        SigningTrustJournal,
        TrustJournalDenied,
        canonical_registry_payload,
        registry_digest,
    )
    from src.governance.store import SqliteStore

    controllers = {name: Ed25519PrivateKey.generate() for name in ("destination", "readback")}
    with _target(harness) as target, closing(SqliteStore(str(tmp_path / "trust.sqlite"))) as store:
        authorization = _authorization(harness, target)
        target.commit_queued(authorization, _action())
        result, receipt, proof = _observe(harness, authorization, _action())
        journal = SigningTrustJournal(store, controller_keys={name: _public(key) for name, key in controllers.items()})
        histories = {}
        for domain, role in (("destination", "destination"), ("readback", "observer")):
            envelope = {"domain": domain, "revision": 1, "previous_sha256": "0" * 64,
                        "keys": [{"key_id": harness["descriptor"][role + "_key_id"],
                                  "public_key_hex": harness["descriptor"][role + "_public_key_hex"], "state": "active"}]}
            envelope["signature_hex"] = controllers[domain].sign(canonical_registry_payload(envelope)).hex()
            journal.publish(envelope)
            histories[domain] = envelope
        arguments = dict(authorization=authorization, action_bytes=_action(), descriptor=harness["descriptor"],
                         result=result, destination_receipt=receipt, readback_attestation=proof)
        assert verify_journaled_queued_action_evidence(trust_journal=journal, **arguments).outcome == "succeeded"
        previous = histories["readback"]
        replacement = {"key_id": "replacement", "public_key_hex": _public(Ed25519PrivateKey.generate()), "state": "staged"}
        staged = {"domain": "readback", "revision": 2, "previous_sha256": registry_digest(previous),
                  "keys": [previous["keys"][0], replacement]}
        staged["signature_hex"] = controllers["readback"].sign(canonical_registry_payload(staged)).hex()
        journal.publish(staged)
        revoked = {"domain": "readback", "revision": 3, "previous_sha256": registry_digest(staged),
                   "keys": [{**previous["keys"][0], "state": "revoked"}, {**replacement, "state": "active"}]}
        revoked["signature_hex"] = controllers["readback"].sign(canonical_registry_payload(revoked)).hex()
        journal.publish(revoked)
        with pytest.raises(TrustJournalDenied):
            verify_journaled_queued_action_evidence(trust_journal=journal, **arguments)


def test_historical_verifier_never_relaxes_signed_commit_window(harness):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        result, receipt = target.commit_queued(authorization, _action())
        assert verify_queued_authorization(authorization, descriptor=harness["descriptor"], action_bytes=_action())
        receipt["committed_at"] = authorization["expires_at"]
        receipt["signature_hex"] = harness["keys"]["destination"].sign(canonical_queued_receipt_payload(receipt)).hex()
        with pytest.raises(UntrustedReceipt, match="window"):
            verify_queued_destination_receipt(receipt, authorization=authorization, action_bytes=_action(),
                                              descriptor=harness["descriptor"], result=result)


def test_utf8_limit_does_not_bypass_canonical_action_byte_limit():
    with pytest.raises(ValueError, match="canonical byte limit"):
        _action("\x00" * 1024)


def test_unknown_persisted_contract_version_is_not_adopted(harness):
    with _target(harness) as target:
        name = "ab_queued_destination_binding_v2_deny_update"
        target.db.execute("DROP TRIGGER " + name)
        target.db.execute("PRAGMA ignore_check_constraints=ON")
        target.db.execute("UPDATE ab_queued_destination_binding_v2 SET version=3")
        target.db.execute("PRAGMA ignore_check_constraints=OFF")
        target.db.execute(_QUEUED_TRIGGER_SQL[name])
    with pytest.raises(ValueError, match="unsupported"):
        _target(harness)


@pytest.mark.parametrize("deadline", ["authorization", "lease"])
def test_signer_cannot_advance_destination_past_deadline_before_effect_insert(harness, deadline):
    with _target(harness) as target:
        authorization = _authorization(harness, target)
        original_sign = target.sign
        expires = (authorization["expires_at"] if deadline == "authorization" else
                   target.db.execute("SELECT expires_seconds FROM ab_destination_fences").fetchone()[0])
        calls = []
        def sign_after_deadline(payload):
            calls.append(payload)
            signature = original_sign(payload)
            harness["clock"][0] = expires + 0.01
            return signature
        target.sign = sign_after_deadline
        with pytest.raises((UntrustedReceipt, SqliteFenceDenied)):
            target.commit_queued(authorization, _action())
        assert len(calls) == 1
        assert _count(target) == 0
