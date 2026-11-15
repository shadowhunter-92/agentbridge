"""Retained local payload bounds; real SQLite/crypto, no provider or PG claim."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
from threading import Barrier

import pytest

from examples.stripe_style_mock import (
    MockCapacityDenied, MockRequestConflict, MockStorageLimits,
    StripeStyleMock, WebhookInbox, WebhookRejected, sign_webhook,
)
from src.governance.budget import Budget, BudgetManager
from src.governance.fenced_sqlite_destination import FencedSqliteTarget
from src.governance.operation_ledger import OperationLedger
from src.governance.sandbox_readback import ObservationUnavailable
from src.governance.store import SqliteStore
from tests.test_stripe_style_mock import (
    SECRET, STAMP, accept, count_effects, event_body, observe,
    offline_only as offline_only, setup as setup,
)


def limits(*, records=10, size=1_000_000, entry=65_536):
    return MockStorageLimits(records, size, min(entry, size))


def stored_usage(db):
    # Independent reference calculation: bytes of every retained scalar/BLOB,
    # including repeated identity/fingerprint/digest data, not just JSON bytes.
    rows = []
    for table in ("mock_stripe_attempts", "sandbox_effects", "mock_stripe_webhooks"):
        rows.extend(tuple(row) for row in db.execute("SELECT * FROM " + table))
    sizes = [sum(len(value if isinstance(value, bytes) else value.encode("utf-8")) for value in row)
             for row in rows]
    return len(rows), sum(sizes), max(sizes, default=0)


def test_defaults_and_exact_monotone_shared_payload_accounting(setup):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        initial = mock.capacity()
        assert initial == {"max_records": 10_000, "max_bytes": 16 * 1024 * 1024,
                           "max_entry_bytes": 65_536, "used_records": 0, "used_bytes": 0}
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        with WebhookInbox(path) as inbox:
            accept(inbox, event_body())
            after = inbox.capacity()
            expected = stored_usage(inbox.db)
            assert after["used_records"] == expected[0] == 3
            assert after["used_bytes"] == expected[1] > 0
            assert mock.capacity() == after
            assert accept(inbox, event_body())["duplicate"] is True
            assert inbox.capacity() == after


@pytest.mark.parametrize("field,value", [
    ("max_records", True), ("max_records", 0), ("max_records", 100_001), ("max_records", 2.5),
    ("max_bytes", 0), ("max_bytes", 536_870_913), ("max_entry_bytes", 0),
    ("max_entry_bytes", 1_048_577), ("max_entry_bytes", "20"),
])
def test_limits_reject_unbounded_or_untyped_values(field, value):
    with pytest.raises(MockCapacityDenied):
        MockStorageLimits(**{field: value})


def test_per_entry_cannot_exceed_aggregate():
    with pytest.raises(MockCapacityDenied):
        MockStorageLimits(10, 100, 101)


@pytest.mark.parametrize("kind", ["mock", "inbox"])
@pytest.mark.parametrize("changed", ["more-records", "more-bytes", "more-entry", "stricter"])
def test_reopen_cannot_reconfigure_persisted_policy(setup, kind, changed):
    path, writer, _, request = setup
    policy = limits(records=3, size=10_000, entry=1000)
    changes = {"more-records": {"max_records": 4}, "more-bytes": {"max_bytes": 20_000},
               "more-entry": {"max_entry_bytes": 2000}, "stricter": {"max_records": 2}}
    if kind == "mock":
        factory = lambda value: StripeStyleMock(path, target_id=request.target_id, sign=writer.sign, limits=value)
    else:
        factory = lambda value: WebhookInbox(path, limits=value)
    with factory(policy):
        pass
    with pytest.raises(MockCapacityDenied, match="cannot be changed"):
        factory(replace(policy, **changes[changed]))
    with factory(None) as reopened:
        assert reopened.capacity()["max_records"] == 3
    with factory(policy) as reopened:
        assert reopened.capacity()["max_bytes"] == 10_000


def test_record_saturation_preserves_duplicate_binding_and_success_readback(setup):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign, limits=limits(records=2)) as mock:
        epoch = mock.acquire(owner="worker")
        mock.confirm(request, owner="worker", epoch=epoch)
        before = mock.capacity()
        with pytest.raises(MockCapacityDenied):
            mock.confirm(replace(request, operation_id="another"), owner="worker", epoch=epoch)
        with pytest.raises(MockRequestConflict, match="no resend"):
            mock.confirm(request, owner="worker", epoch=epoch)
        with pytest.raises(MockRequestConflict, match="different arguments"):
            mock.confirm(replace(request, amount=600), owner="worker", epoch=epoch)
        assert mock.capacity() == before
    assert observe(path, writer, reader, request)[0] == request.succeeded_intent()
    assert count_effects(path) == 1


def test_post_attempt_saturation_holds_original_unknown_exposure_and_never_resends(setup, tmp_path):
    path, writer, reader, request = setup
    store = SqliteStore(str(tmp_path / "governance.sqlite"))
    try:
        manager = BudgetManager(store)
        manager.set_budget(request.agent_id, Budget(spend_limit=10))
        token, why = manager.reserve(request.agent_id, 5)
        assert token, why
        ledger = OperationLedger(store)
        ledger.claim(request.agent_id, request.operation_id, request.fingerprint, reservation_token=token)
        original = store.get_budget(request.agent_id)
        with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign, limits=limits(records=1)) as mock:
            epoch = mock.acquire(owner="worker")
            with pytest.raises(MockCapacityDenied, match="outcome unknown, no resend"):
                mock.confirm(request, owner="worker", epoch=epoch)
            assert mock.capacity()["used_records"] == 1
        with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as restarted:
            with pytest.raises(MockRequestConflict):
                restarted.confirm(request, owner="worker", epoch=epoch)
        with pytest.raises(ObservationUnavailable):
            observe(path, writer, reader, request)
        assert count_effects(path) == 0
        assert ledger.get(request.agent_id, request.operation_id)["state"] == "unknown"
        assert store.get_budget(request.agent_id) == original
    finally:
        store.close()


def test_effect_and_attempt_bytes_share_one_exact_aggregate_limit(setup, tmp_path):
    path, writer, reader, request = setup
    reference = str(tmp_path / "reference.sqlite")
    with StripeStyleMock(reference, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        _, total, largest = stored_usage(mock.target.db)
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign,
                         limits=limits(size=total, entry=largest)) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        assert mock.capacity()["used_bytes"] == total
        with WebhookInbox(path) as inbox:
            with pytest.raises(MockCapacityDenied):
                accept(inbox, event_body())
        assert mock.capacity()["used_records"] == 2
    assert observe(path, writer, reader, request)[0]["status"] == "succeeded"


def test_entry_saturation_refuses_new_attempt_before_any_effect(setup, tmp_path):
    path, writer, _, request = setup
    reference = str(tmp_path / "reference.sqlite")
    with StripeStyleMock(reference, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        row = tuple(mock.target.db.execute("SELECT * FROM mock_stripe_attempts").fetchone())
        size = sum(len(value if isinstance(value, bytes) else value.encode()) for value in row)
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign,
                         limits=limits(entry=size - 1)) as mock:
        with pytest.raises(MockCapacityDenied):
            mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        assert mock.capacity()["used_records"] == 0 and count_effects(path) == 0


def test_entry_saturation_after_attempt_keeps_unknown_and_no_resend(setup, tmp_path):
    path, writer, reader, request = setup
    with StripeStyleMock(str(tmp_path / "reference.sqlite"), target_id=request.target_id, sign=writer.sign) as ref:
        ref.confirm(request, owner="worker", epoch=ref.acquire(owner="worker"))
        sizes = []
        for table in ("mock_stripe_attempts", "sandbox_effects"):
            row = ref.target.db.execute("SELECT * FROM " + table).fetchone()
            sizes.append(sum(len(value if isinstance(value, bytes) else value.encode()) for value in row))
    assert sizes[0] < sizes[1]
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign, limits=limits(entry=sizes[1] - 1)) as mock:
        epoch = mock.acquire(owner="worker")
        with pytest.raises(MockCapacityDenied, match="outcome unknown, no resend"):
            mock.confirm(request, owner="worker", epoch=epoch)
        assert mock.capacity()["used_records"] == 1
        assert mock.capacity()["used_bytes"] == sizes[0]
        with pytest.raises(MockRequestConflict):
            mock.confirm(request, owner="worker", epoch=epoch)
    assert count_effects(path) == 0
    with pytest.raises(ObservationUnavailable):
        observe(path, writer, reader, request)


def test_utf8_text_and_blob_bytes_not_character_counts(tmp_path):
    path = str(tmp_path / "utf8.sqlite")
    values = ("evt_雪", "f" * 64, '{"note":"☃"}'.encode("utf-8"))
    expected = sum(len(value if isinstance(value, bytes) else value.encode("utf-8")) for value in values)
    assert expected > sum(len(value) for value in values)
    with WebhookInbox(path, limits=limits(size=expected, entry=expected)) as inbox:
        # Direct compatibility INSERT still passes the SQL capacity guard;
        # it is not an authenticated webhook or a settlement assertion.
        inbox.db.execute("INSERT INTO mock_stripe_webhooks VALUES(?,?,?)", values)
        assert inbox.capacity()["used_bytes"] == expected
        with pytest.raises(sqlite3.IntegrityError, match="capacity reached"):
            inbox.db.execute("INSERT INTO mock_stripe_webhooks VALUES('x','y',?)", (b"z",))
        assert inbox.capacity()["used_records"] == 1


def test_canonical_webhook_storage_counts_actual_serialized_bytes(tmp_path):
    body = json.loads(event_body())
    body["unicode"] = "雪☃"
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    expected = len(body["id"].encode()) + 64 + len(canonical)
    with WebhookInbox(str(tmp_path / "inbox.sqlite"), limits=limits(size=expected, entry=expected)) as inbox:
        header = sign_webhook(raw, secret=SECRET, timestamp=STAMP)
        inbox.accept(raw, header, secret=SECRET, now=STAMP)
        assert inbox.capacity()["used_bytes"] == expected


@pytest.mark.parametrize("sql", [
    "UPDATE mock_stripe_capacity_v1 SET max_records=100000",
    "DELETE FROM mock_stripe_capacity_v1",
    "INSERT OR REPLACE INTO mock_stripe_capacity_v1 VALUES(1,1,100000,1000000,65536)",
])
def test_policy_cannot_be_loosened_removed_or_replaced(tmp_path, sql):
    with WebhookInbox(str(tmp_path / "inbox.sqlite"), limits=limits(records=1)) as inbox:
        accept(inbox, event_body())
        before = inbox.capacity()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            inbox.db.execute(sql)
        assert inbox.capacity() == before


def test_saturated_inbox_acknowledges_duplicates_but_never_replaces_content(tmp_path):
    with WebhookInbox(str(tmp_path / "inbox.sqlite"), limits=limits(records=1)) as inbox:
        body = event_body()
        accept(inbox, body)
        before = inbox.capacity()
        assert accept(inbox, body)["duplicate"] is True
        changed = json.loads(body)
        changed["data"]["object"]["id"] = "pi_changed"
        with pytest.raises(WebhookRejected, match="different content"):
            accept(inbox, json.dumps(changed).encode())
        with pytest.raises(MockCapacityDenied):
            accept(inbox, event_body(event_id="evt_other"))
        assert inbox.capacity() == before


@pytest.mark.parametrize("table", ["mock_stripe_attempts", "sandbox_effects", "mock_stripe_webhooks"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "REPLACE"])
def test_payload_cannot_be_modified_evicted_or_replaced(setup, table, operation):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        with WebhookInbox(path) as inbox:
            accept(inbox, event_body())
        db = mock.target.db
        before = mock.capacity()
        if operation == "REPLACE":
            query = "INSERT OR REPLACE INTO " + table + " SELECT * FROM " + table
        elif operation == "DELETE":
            query = "DELETE FROM " + table
        else:
            field = {"mock_stripe_attempts": "fingerprint", "sandbox_effects": "outcome",
                     "mock_stripe_webhooks": "event_sha256"}[table]
            query = "UPDATE " + table + " SET " + field + "='changed'"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(query)
        assert mock.capacity() == before


@pytest.mark.parametrize("object_name,is_trigger", [
    ("mock_stripe_attempts", False), ("sandbox_effects", False), ("mock_stripe_webhooks", False),
    ("mock_stripe_capacity_v1", False), ("mock_storage_sandbox_effects_insert_v1", True),
])
def test_selective_schema_loss_refuses_reopen_without_healing(setup, object_name, is_trigger):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
    with sqlite3.connect(path) as admin:
        admin.execute(("DROP TRIGGER " if is_trigger else "DROP TABLE ") + object_name)
    with pytest.raises(MockCapacityDenied):
        StripeStyleMock(path, target_id=request.target_id, sign=writer.sign)
    with sqlite3.connect(path) as admin:
        assert admin.execute("SELECT 1 FROM sqlite_master WHERE name=?", (object_name,)).fetchone() is None


def test_modified_guard_refuses_current_and_reopened_writer_but_preserves_readback(setup):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        mock.confirm(request, owner="worker", epoch=mock.acquire(owner="worker"))
        db = mock.target.db
        # Database-owner DDL is outside the boundary; qualification must refuse
        # a later ordinary writer rather than silently repair/rebudget history.
        db.execute("DROP TRIGGER mock_storage_mock_stripe_webhooks_insert_v1")
        changed = "CREATE TRIGGER mock_storage_mock_stripe_webhooks_insert_v1 AFTER INSERT ON mock_stripe_webhooks BEGIN SELECT 1; END"
        db.execute(changed)
        with pytest.raises(MockCapacityDenied, match="modified"):
            mock.capacity()
        with pytest.raises(MockCapacityDenied, match="modified"):
            StripeStyleMock(path, target_id=request.target_id, sign=writer.sign)
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='mock_storage_mock_stripe_webhooks_insert_v1'").fetchone()[0] == changed
    assert observe(path, writer, reader, request)[0] == request.succeeded_intent()


@pytest.mark.parametrize("name", ["MOCK_STRIPE_CAPACITY_V1", "sandbox_effects", "mock_stripe_webhooks"])
def test_temp_shadows_cannot_select_another_policy_or_history(tmp_path, name):
    with WebhookInbox(str(tmp_path / "inbox.sqlite"), limits=limits(records=1)) as inbox:
        inbox.db.execute("CREATE TEMP TABLE " + name + " (x)")
        with pytest.raises(MockCapacityDenied, match="TEMP"):
            accept(inbox, event_body())
        assert inbox.db.execute("SELECT count(*) FROM main.mock_stripe_webhooks").fetchone()[0] == 0


def test_attached_namespace_is_not_a_capacity_expansion_path(tmp_path):
    with WebhookInbox(str(tmp_path / "inbox.sqlite")) as inbox:
        inbox.db.execute("ATTACH DATABASE ':memory:' AS other")
        with pytest.raises(MockCapacityDenied, match="attached"):
            inbox.capacity()


def test_existing_utf16_storage_is_refused_without_new_policy(tmp_path):
    path = str(tmp_path / "utf16.sqlite")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA encoding='UTF-16'")
        db.execute("CREATE TABLE existing(x)")
    with pytest.raises(MockCapacityDenied, match="UTF-8"):
        WebhookInbox(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='mock_stripe_capacity_v1'").fetchone() is None


def test_existing_unbounded_history_is_counted_without_reset(tmp_path):
    path = str(tmp_path / "legacy.sqlite")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE mock_stripe_webhooks (event_id TEXT PRIMARY KEY, event_sha256 TEXT NOT NULL, event_json BLOB NOT NULL)")
        db.executemany("INSERT INTO mock_stripe_webhooks VALUES(?,?,?)", [("a", "f", b"{}"), ("b", "f", b"{}")])
    with pytest.raises(MockCapacityDenied, match="exceeds"):
        WebhookInbox(path, limits=limits(records=1))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 2
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='mock_stripe_capacity_v1'").fetchone() is None
    with WebhookInbox(path, limits=limits(records=2)) as inbox:
        assert inbox.capacity()["used_records"] == 2


@pytest.mark.parametrize("values", [(None, "f", b"{}"), ("evt", b"f", b"{}"), ("evt", "f", "{}")])
@pytest.mark.parametrize("legacy", [False, True])
def test_malformed_payload_types_cannot_escape_byte_accounting(tmp_path, values, legacy):
    path = str(tmp_path / "malformed.sqlite")
    if legacy:
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE mock_stripe_webhooks (event_id TEXT PRIMARY KEY, event_sha256 TEXT NOT NULL, event_json BLOB NOT NULL)")
            db.execute("INSERT INTO mock_stripe_webhooks VALUES(?,?,?)", values)
        with pytest.raises(MockCapacityDenied, match="historical.*type"):
            WebhookInbox(path)
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT count(*) FROM mock_stripe_webhooks").fetchone()[0] == 1
            assert db.execute("SELECT 1 FROM sqlite_master WHERE name='mock_stripe_capacity_v1'").fetchone() is None
    else:
        with WebhookInbox(path) as inbox:
            with pytest.raises(sqlite3.IntegrityError, match="value type"):
                inbox.db.execute("INSERT INTO mock_stripe_webhooks VALUES(?,?,?)", values)
            assert inbox.capacity()["used_records"] == inbox.capacity()["used_bytes"] == 0


def test_existing_fenced_target_writer_cannot_bypass_effect_capacity(setup):
    path, writer, _, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign, limits=limits(records=1)) as mock:
        epoch = mock.acquire(owner="worker")
        with FencedSqliteTarget(path, sign=writer.sign) as direct:
            direct.commit(scope=mock.scope, owner="worker", epoch=epoch, agent_id="legacy", operation_id="one", fingerprint="f")
            with pytest.raises(sqlite3.IntegrityError, match="capacity reached"):
                direct.commit(scope=mock.scope, owner="worker", epoch=epoch, agent_id="legacy", operation_id="two", fingerprint="f")
        assert mock.capacity()["used_records"] == 1 and count_effects(path) == 1


@pytest.mark.parametrize("byte_limit", [False, True])
def test_concurrent_inbox_inserts_respect_shared_count_and_byte_limits(tmp_path, byte_limit):
    path = str(tmp_path / "concurrent.sqlite")
    body = event_body(event_id="evt_0")
    value = json.loads(body)
    one_size = len(value["id"].encode()) + 64 + len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    policy = limits(records=10 if byte_limit else 2, size=2 * one_size if byte_limit else 1_000_000)
    with WebhookInbox(path, limits=policy):
        pass
    barrier = Barrier(4)

    def write(index):
        with WebhookInbox(path) as inbox:
            barrier.wait(timeout=10)
            try:
                accept(inbox, event_body(event_id="evt_" + str(index)))
                return "accepted"
            except MockCapacityDenied:
                return "full"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(4)))
    assert results.count("accepted") == results.count("full") == 2
    with WebhookInbox(path) as inbox:
        assert inbox.capacity()["used_records"] == 2
        assert inbox.capacity()["used_bytes"] == 2 * one_size


def test_concurrent_distinct_payments_keep_one_effect_and_both_attempts(setup):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign, limits=limits(records=3)) as mock:
        epoch = mock.acquire(owner="worker", ttl_seconds=60)
    barrier = Barrier(2)

    def write(index):
        current = replace(request, operation_id="parallel-" + str(index))
        with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
            barrier.wait(timeout=10)
            try:
                mock.confirm(current, owner="worker", epoch=epoch)
                return "success", current
            except MockCapacityDenied:
                return "unknown", current

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, range(2)))
    assert sorted(state for state, _ in results) == ["success", "unknown"]
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        assert mock.capacity()["used_records"] == 3
        for state, current in results:
            with pytest.raises(MockRequestConflict):
                mock.confirm(current, owner="worker", epoch=epoch)
            if state == "success":
                assert observe(path, writer, reader, current)[0]["status"] == "succeeded"
            else:
                with pytest.raises(ObservationUnavailable):
                    observe(path, writer, reader, current)
    assert count_effects(path) == 1


def test_inbox_and_payment_share_capacity_under_concurrent_commits(setup):
    path, writer, reader, request = setup
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign, limits=limits(records=2)) as mock:
        epoch = mock.acquire(owner="worker", ttl_seconds=60)
    barrier = Barrier(2)

    def notify():
        with WebhookInbox(path) as inbox:
            barrier.wait(timeout=10)
            try:
                accept(inbox, event_body())
                return "accepted"
            except MockCapacityDenied:
                return "full"

    def confirm():
        with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
            barrier.wait(timeout=10)
            try:
                mock.confirm(request, owner="worker", epoch=epoch)
                return "success"
            except MockCapacityDenied:
                return "unknown"

    with ThreadPoolExecutor(max_workers=2) as pool:
        notification, payment = pool.submit(notify), pool.submit(confirm)
        outcomes = notification.result(), payment.result()
    assert outcomes in {("accepted", "unknown"), ("full", "success")}
    with StripeStyleMock(path, target_id=request.target_id, sign=writer.sign) as mock:
        assert mock.capacity()["used_records"] == 2
        with pytest.raises(MockRequestConflict):
            mock.confirm(request, owner="worker", epoch=epoch)
    if outcomes[1] == "success":
        assert observe(path, writer, reader, request)[0] == request.succeeded_intent()
    else:
        with pytest.raises(ObservationUnavailable):
            observe(path, writer, reader, request)
