"""Offline reference contract: real SQLite/crypto, no Stripe/network/credentials."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import socket
import sqlite3
from threading import Barrier

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from examples.stripe_style_mock import (
    MockRequestConflict, PaymentIntentRequest, StripeStyleMock, StripeStyleReadback,
    WebhookInbox, WebhookRejected, sign_webhook, verify_payment_evidence,
)
from src.governance.budget import Budget, BudgetManager
from src.governance.fenced_sqlite_destination import SqliteFenceDenied
from src.governance.operation_ledger import OperationConflict, OperationLedger
from src.governance.sandbox_readback import ObservationUnavailable
from src.governance.store import SqliteStore


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "test")

    def forbidden(*_, **__):
        raise AssertionError("network use forbidden in offline mock tests")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def setup(tmp_path):
    return (str(tmp_path / "target.sqlite"), Ed25519PrivateKey.generate(),
            Ed25519PrivateKey.generate(), PaymentIntentRequest("payments", "buyer", "order-001", 500))


def observe(path, writer, reader, request):
    with StripeStyleReadback(path, destination_public_key_hex=public(writer), sign=reader.sign) as ro:
        return ro.observe_payment(request)


def count_effects(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT count(*) FROM sandbox_effects").fetchone()[0]


def test_roundtrip_uses_existing_fence_observer_and_verifier(setup):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        epoch = mock.acquire(owner="worker")
        intent, receipt = mock.confirm(request, owner="worker", epoch=epoch)
        assert intent == request.succeeded_intent()
        assert intent["livemode"] is False and intent["id"].startswith("pi_mock_")
        assert receipt["fingerprint"] == request.fingerprint
        with StripeStyleReadback(path, destination_public_key_hex=public(writer), sign=reader.sign) as ro:
            observed_intent, observed_receipt, proof = ro.observe_payment(request)
            assert observed_intent == intent and observed_receipt == receipt
            with pytest.raises(sqlite3.OperationalError):
                ro._db.execute("DELETE FROM sandbox_effects")
        evidence = verify_payment_evidence(request, intent, receipt, proof,
                                           destination_key_hex=public(writer), readback_key_hex=public(reader))
        assert evidence.fingerprint == request.fingerprint and evidence.outcome == "succeeded"
    assert count_effects(path) == 1


def test_lost_ack_preserves_original_unknown_and_budget_until_separate_reconciliation(setup, tmp_path):
    path, writer, reader, request = setup
    store = SqliteStore(str(tmp_path / "governance.sqlite"))
    try:
        budget = BudgetManager(store)
        budget.set_budget(request.agent_id, Budget(spend_limit=10))
        token, why = budget.reserve(request.agent_id, 5)
        assert token, why
        ledger = OperationLedger(store)
        ledger.claim(request.agent_id, request.operation_id, request.fingerprint, reservation_token=token)
        before_budget = store.get_budget(request.agent_id)
        with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
            epoch = mock.acquire(owner="worker")
            with pytest.raises(TimeoutError, match="acknowledgement dropped"):
                mock.confirm(request, owner="worker", epoch=epoch, lose_ack=True)
            with pytest.raises(MockRequestConflict, match="no resend"):
                mock.confirm(request, owner="worker", epoch=epoch)
        with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as restarted:
            with pytest.raises(MockRequestConflict):
                restarted.confirm(request, owner="worker", epoch=epoch)
        intent, receipt, proof = observe(path, writer, reader, request)
        verify_payment_evidence(request, intent, receipt, proof,
                                destination_key_hex=public(writer), readback_key_hex=public(reader))
        assert ledger.get(request.agent_id, request.operation_id)["state"] == "unknown"
        assert store.get_budget(request.agent_id) == before_budget
        with pytest.raises(OperationConflict):
            ledger.claim(request.agent_id, request.operation_id, request.fingerprint)
        assert count_effects(path) == 1
    finally:
        store.close()


def test_persistent_key_argument_mismatch_and_no_cached_resend(setup):
    path, writer, _, request = setup
    changed = replace(request, amount=600)
    assert changed.idempotency_key == request.idempotency_key
    assert changed.fingerprint != request.fingerprint
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        epoch = mock.acquire(owner="worker")
        mock.confirm(request, owner="worker", epoch=epoch)
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as restarted:
        with pytest.raises(MockRequestConflict, match="different arguments"):
            restarted.confirm(changed, owner="worker", epoch=epoch)
        with pytest.raises(MockRequestConflict, match="readback only"):
            restarted.confirm(request, owner="worker", epoch=epoch)
    assert count_effects(path) == 1


@pytest.mark.parametrize("field,value", [
    ("amount", True), ("amount", 0), ("amount", -1), ("amount", 1.2), ("amount", "500"),
    ("amount", 100_000_001), ("currency", "USD"), ("currency", "eur"),
    ("target_id", ""), ("target_id", "https://stripe.com"), ("agent_id", "x" * 129),
    ("operation_id", "bad\noperation"), ("operation_id", None),
])
def test_invalid_request_fails_before_destination(setup, field, value):
    with pytest.raises(ValueError):
        replace(setup[3], **{field: value})


def test_operator_target_binding_cannot_be_changed_or_bypassed(setup):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        epoch = mock.acquire(owner="worker")
        with pytest.raises(ValueError, match="operator target"):
            mock.confirm(replace(request, target_id="other"), owner="worker", epoch=epoch)
        assert mock.target.db.execute("SELECT count(*) FROM mock_stripe_attempts").fetchone()[0] == 0
    with pytest.raises(ValueError, match="another target"):
        StripeStyleMock(path, target_id="other", sign=writer.sign)
    assert count_effects(path) == 0


def test_stale_and_wrong_owner_refusal_preserves_attempt_without_effect(setup):
    path, writer, reader, request = setup
    clock = [1_790_000_000.0]
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as old, StripeStyleMock(
            path, target_id=request.target_id, sign=writer.sign) as successor:
        for mock in (old, successor):
            mock.target.db.create_function("julianday", 1, lambda _: clock[0] / 86400 + 2440587.5)
        epoch = old.acquire(owner="old", ttl_seconds=1)
        with pytest.raises(SqliteFenceDenied):
            successor.acquire(owner="new")
        clock[0] += 2
        newer = successor.acquire(owner="new")
        assert newer > epoch
        with pytest.raises(SqliteFenceDenied):
            old.confirm(request, owner="old", epoch=epoch)
        with pytest.raises(MockRequestConflict):
            successor.confirm(request, owner="new", epoch=newer)
        with pytest.raises(ObservationUnavailable):
            observe(path, writer, reader, request)
        with pytest.raises(SqliteFenceDenied):
            successor.confirm(replace(request, operation_id="wrong-owner"), owner="intruder", epoch=newer)
        successor.confirm(replace(request, operation_id="new-order"), owner="new", epoch=newer)
    assert count_effects(path) == 1


@pytest.mark.parametrize("field,value", [("owner", ""), ("epoch", True), ("epoch", 0),
                                         ("epoch", 1.3), ("lose_ack", 1)])
def test_invalid_fence_inputs_leave_no_attempt(setup, field, value):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        kwargs = dict(owner="worker", epoch=1, lose_ack=False)
        kwargs[field] = value
        with pytest.raises(ValueError):
            mock.confirm(request, **kwargs)
        assert mock.target.db.execute("SELECT count(*) FROM mock_stripe_attempts").fetchone()[0] == 0


def test_crash_between_attempt_and_effect_never_becomes_permission_to_resend(setup, monkeypatch):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        epoch = mock.acquire(owner="worker")

        def crash(**_):
            raise RuntimeError("simulated pre-effect crash")

        monkeypatch.setattr(mock.target, "commit", crash)
        with pytest.raises(RuntimeError, match="pre-effect crash"):
            mock.confirm(request, owner="worker", epoch=epoch)
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as restarted:
        with pytest.raises(MockRequestConflict):
            restarted.confirm(request, owner="worker", epoch=epoch)
    with pytest.raises(ObservationUnavailable):
        observe(path, writer, reader, request)
    assert count_effects(path) == 0


def test_destination_signer_failure_has_no_effect_and_no_automatic_retry(setup):
    path, _, reader, request = setup
    writer = Ed25519PrivateKey.generate()
    with StripeStyleMock(path, target_id=request.target_id, sign=lambda _: b"invalid") as mock:
        epoch = mock.acquire(owner="worker")
        with pytest.raises(ValueError, match="signature invalid"):
            mock.confirm(request, owner="worker", epoch=epoch)
        with pytest.raises(MockRequestConflict):
            mock.confirm(request, owner="worker", epoch=epoch)
    assert count_effects(path) == 0
    with pytest.raises(ObservationUnavailable):
        observe(path, writer, reader, request)


@pytest.mark.parametrize("different_arguments", [False, True])
def test_parallel_collision_one_attempt_one_effect(setup, different_arguments):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        epoch = mock.acquire(owner="worker", ttl_seconds=60)
    requests = [request, replace(request, amount=600) if different_arguments else request]
    barrier = Barrier(2)

    def send(req):
        with StripeStyleMock(path, target_id=req.target_id, sign=writer.sign) as mock:
            barrier.wait(timeout=10)
            try:
                mock.confirm(req, owner="worker", epoch=epoch)
                return "success", req
            except MockRequestConflict:
                return "conflict", req

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, requests))
    assert sorted(result[0] for result in results) == ["conflict", "success"]
    winner = next(req for state, req in results if state == "success")
    intent, receipt, proof = observe(path, writer, reader, winner)
    verify_payment_evidence(winner, intent, receipt, proof,
                            destination_key_hex=public(writer), readback_key_hex=public(reader))
    assert count_effects(path) == 1


@pytest.mark.parametrize("field,value", [("amount", 600), ("operation_id", "missing"),
                                         ("agent_id", "other"), ("target_id", "other")])
def test_readback_requires_exact_expected_request(setup, field, value):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
    with pytest.raises(ObservationUnavailable):
        observe(path, writer, reader, replace(request, **{field: value}))


@pytest.mark.parametrize("column,value", [("outcome", "failed"), ("external_reference", "counterfeit"),
                                          ("fingerprint", "wrong"), ("receipt_json", "{}")])
def test_readback_rejects_corrupt_persisted_destination_state(setup, column, value):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        mock.target.db.execute(f"UPDATE sandbox_effects SET {column}=?", (value,))
    with pytest.raises(ObservationUnavailable):
        observe(path, writer, reader, request)


@pytest.mark.parametrize("field,value", [("amount", 1), ("currency", "eur"), ("status", "processing"),
                                         ("id", "pi_counterfeit"), ("livemode", True)])
def test_offline_verifier_rejects_mismatched_payment_projection(setup, field, value):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
    intent, receipt, proof = observe(path, writer, reader, request)
    intent[field] = value
    with pytest.raises(ValueError):
        verify_payment_evidence(request, intent, receipt, proof,
                                destination_key_hex=public(writer), readback_key_hex=public(reader))


@pytest.mark.parametrize("changed", ["destination-key", "observer-key", "proof", "receipt"])
def test_offline_verifier_rejects_forged_pins_and_signatures(setup, changed):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
    intent, receipt, proof = observe(path, writer, reader, request)
    keys = dict(destination_key_hex=public(writer), readback_key_hex=public(reader))
    if changed == "destination-key":
        keys["destination_key_hex"] = public(Ed25519PrivateKey.generate())
    elif changed == "observer-key":
        keys["readback_key_hex"] = public(Ed25519PrivateKey.generate())
    elif changed == "proof":
        proof["source_evidence_sha256"] = "0" * 64
    else:
        receipt["signature_hex"] = "0" * 128
    with pytest.raises(ValueError):
        verify_payment_evidence(request, intent, receipt, proof, **keys)


@pytest.mark.parametrize("table", ["mock_stripe_binding", "mock_stripe_attempts"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_request_records_are_immutable_via_ordinary_sql(setup, table, verb):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        query = f"DELETE FROM {table}" if verb == "DELETE" else f"UPDATE {table} SET " + (
            "target_id='other'" if table.endswith("binding") else "fingerprint='changed'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            mock.target.db.execute(query)


SECRET = bytes(range(32))  # Public synthetic fixture value; never an account credential.
STAMP = 1_790_000_000


def event_body(*, event_id="evt_mock_1", event_type="payment_intent.succeeded", amount=500):
    intent = PaymentIntentRequest("payments", "buyer", "order-001", amount).succeeded_intent()
    if event_type == "payment_intent.processing":
        intent["status"] = "processing"
    return json.dumps({"id": event_id, "object": "event", "livemode": False,
                       "type": event_type, "data": {"object": intent}}, sort_keys=True).encode()


def accept(inbox, body, *, timestamp=STAMP, now=STAMP, header=None):
    return inbox.accept(body, header or sign_webhook(body, secret=SECRET, timestamp=timestamp),
                        secret=SECRET, now=now)


def test_raw_body_hmac_and_durable_freshly_signed_duplicates(tmp_path):
    path, body = str(tmp_path / "inbox.sqlite"), event_body()
    with WebhookInbox(path) as inbox:
        assert accept(inbox, body) == {"event_id": "evt_mock_1", "duplicate": False, "effect_dispatched": False}
        assert accept(inbox, body, timestamp=STAMP + 10, now=STAMP + 10)["duplicate"]
    with WebhookInbox(path) as restarted:
        assert accept(restarted, json.dumps(json.loads(body), separators=(",", ":")).encode())["duplicate"]
        assert restarted.db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 1


@pytest.mark.parametrize("offset", [-300, 300])
def test_timestamp_tolerance_inclusive_boundary(tmp_path, offset):
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        assert not accept(inbox, event_body(), timestamp=STAMP + offset)["duplicate"]


@pytest.mark.parametrize("offset", [-301, 301])
def test_expired_and_future_signatures_rejected_without_inbox_mutation(tmp_path, offset):
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        with pytest.raises(WebhookRejected):
            accept(inbox, event_body(), timestamp=STAMP + offset)
        assert inbox.db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 0


def test_unknown_metadata_and_multiple_rotation_signatures(tmp_path):
    body = event_body()
    header = "v0=ignored,extra=metadata,v1=" + "0" * 64 + "," + sign_webhook(body, secret=SECRET, timestamp=STAMP)
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        assert not accept(inbox, body, header=header)["duplicate"]


def test_timestamp_text_is_not_silently_normalized_before_hmac(tmp_path):
    body = event_body()
    header = sign_webhook(body, secret=SECRET, timestamp=1000).replace("t=1000", "t=01000")
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        with pytest.raises(WebhookRejected, match="canonical timestamp"):
            inbox.accept(body, header, secret=SECRET, now=1000)
        assert inbox.db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["changed-raw", "wrong-secret", "v0-only", "missing-t", "duplicate-t",
                                       "invalid-t", "missing-v1", "short-v1", "disabled-tolerance", "bad-now"])
def test_authentication_failure_records_nothing(tmp_path, failure):
    body = event_body()
    header = sign_webhook(body, secret=SECRET, timestamp=STAMP)
    kwargs = dict(secret=SECRET, now=STAMP)
    if failure == "changed-raw":
        body += b" "
    elif failure == "wrong-secret":
        kwargs["secret"] = b"x" * 32
    elif failure == "v0-only":
        header = header.replace("v1=", "v0=")
    elif failure == "missing-t":
        header = header.split(",", 1)[1]
    elif failure == "duplicate-t":
        header += f",t={STAMP}"
    elif failure == "invalid-t":
        header = header.replace(str(STAMP), "not-a-time")
    elif failure == "missing-v1":
        header = f"t={STAMP}"
    elif failure == "short-v1":
        header = f"t={STAMP},v1=abc"
    elif failure == "disabled-tolerance":
        kwargs["tolerance_seconds"] = 0
    else:
        kwargs["now"] = True
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        with pytest.raises(WebhookRejected):
            inbox.accept(body, header, **kwargs)
        assert inbox.db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 0


def test_event_id_conflict_rejected_and_out_of_order_distinct_notifications_are_harmless(tmp_path):
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        accept(inbox, event_body())
        with pytest.raises(WebhookRejected, match="different content"):
            accept(inbox, event_body(amount=600))
        result = accept(inbox, event_body(event_id="evt_older", event_type="payment_intent.processing"))
        assert result["effect_dispatched"] is False
        assert inbox.db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 2
        assert not inbox.db.execute("SELECT name FROM sqlite_master WHERE name='sandbox_effects'").fetchone()


@pytest.mark.parametrize("body", [b"[]", b"{bad-json}", b"\xff", b'{"id":"x","id":"y"}',
                                 b'{"value":NaN}', b'{"livemode":true}', b"null"])
def test_signed_malformed_event_is_not_accepted(tmp_path, body):
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        with pytest.raises(WebhookRejected):
            accept(inbox, body)
        assert inbox.db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 0


@pytest.mark.parametrize("body,secret,timestamp", [(b"", SECRET, STAMP), (b"x" * 65_537, SECRET, STAMP),
                                                 ("not bytes", SECRET, STAMP), (b"x", b"short", STAMP),
                                                 (b"x", SECRET, True), (b"x", SECRET, -1)],
                         ids=["empty", "oversize", "text", "short-secret", "boolean-time", "negative-time"])
def test_signer_input_bounds(body, secret, timestamp):
    with pytest.raises(WebhookRejected):
        sign_webhook(body, secret=secret, timestamp=timestamp)


def test_parallel_webhook_duplicates_have_one_durable_notification(tmp_path):
    path, body = str(tmp_path / "inbox.sqlite"), event_body()
    with WebhookInbox(path):
        pass
    barrier = Barrier(2)

    def deliver(_):
        with WebhookInbox(path) as inbox:
            barrier.wait(timeout=10)
            return accept(inbox, body)["duplicate"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(deliver, range(2))) == [False, True]
    with WebhookInbox(path) as inbox:
        assert inbox.db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 1


def test_production_refusal_before_write_and_after_construction(setup, tmp_path, monkeypatch):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        epoch = mock.acquire(owner="worker")
        monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
        with pytest.raises(RuntimeError, match="refuses production"):
            mock.confirm(request, owner="worker", epoch=epoch)
        assert count_effects(path) == 0
    refused = tmp_path / "refused.sqlite"
    with pytest.raises(RuntimeError):
        StripeStyleMock(str(refused), target_id=request.target_id, sign=writer.sign)
    with pytest.raises(RuntimeError):
        WebhookInbox(str(refused))
    assert not refused.exists()
