"""SQLite retained revision limits, without changing signed key-state truth."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from examples.qualify_trust_evidence import public, signed_registry
from src.governance.signing_journal_capacity import (
    DDL,
    DEFAULTS,
    HISTORY_DDL,
    TABLE,
    SigningJournalCapacityDenied,
    SigningJournalLimits,
    _statements,
    verify_if_installed,
)
from src.governance.signing_trust_journal import SigningTrustJournal, TrustJournalDenied
from src.governance.store import SqliteStore, sql_atomic
from src.governance.tenant_store import TenantSqliteStore


@pytest.fixture
def journal(tmp_path):
    path = str(tmp_path / "trust.sqlite")
    store = SqliteStore(path)
    controllers = {domain: Ed25519PrivateKey.generate() for domain in ("destination", "readback")}
    pinned = {domain: public(key) for domain, key in controllers.items()}
    trust = SigningTrustJournal(store, controller_keys=pinned)
    keys = [dict(key_id="old", public_key_hex=public(Ed25519PrivateKey.generate()), state="active")]

    def proposal(domain="readback", previous=None, entries=None):
        return signed_registry(controllers[domain], domain, 1 if previous is None else previous["revision"] + 1,
                               previous, keys if entries is None else entries)

    try:
        yield store, trust, proposal, pinned, path
    finally:
        store.close()


def rows(store):
    return [dict(row) for row in store._db.execute("SELECT * FROM signing_trust_revisions ORDER BY domain,revision")]


def size(envelope):
    return len(json.dumps(envelope, sort_keys=True).encode("utf-8"))


@pytest.mark.parametrize("field,value", [("max_records", 0), ("max_records", True), ("max_records", 100001),
                                       ("max_bytes", 536870913), ("max_bytes", 1.5), ("max_entry_bytes", 1048577),
                                       ("max_entry_bytes", 0), ("max_entry_bytes", False)])
def test_limits_refuse_unbounded_or_ambiguous_values(field, value):
    with pytest.raises(SigningJournalCapacityDenied):
        SigningJournalLimits(**{field: value})


def test_lazy_policy_does_not_prevent_initial_tenant_binding(journal):
    store, _, _, pinned, path = journal
    assert store._db.execute("SELECT count(*) AS n FROM " + TABLE).fetchone()["n"] == 0
    scoped = TenantSqliteStore(path, tenant_id="alpha")
    try:
        trust = SigningTrustJournal(scoped, controller_keys=pinned)
        current = trust.capacity()
        assert (current["max_records"], current["max_bytes"], current["max_entry_bytes"]) == (
            DEFAULTS.max_records, DEFAULTS.max_bytes, DEFAULTS.max_entry_bytes)
        assert (current["used_records"], current["used_bytes"]) == (0, 0)
        with pytest.raises(Exception, match="tenant write scope|agentbridge_current_tenant"):
            store._db.execute("UPDATE " + TABLE + " SET max_records=5")
    finally:
        scoped.close()


def test_namespace_count_shrink_restart_and_duplicate_at_capacity(journal):
    store, trust, proposal, pinned, _ = journal
    trust.set_capacity(max_records=2, max_bytes=100000, max_entry_bytes=10000)
    heads = {domain: proposal(domain) for domain in ("destination", "readback")}
    for head in heads.values():
        trust.publish(head)
    before, floors = rows(store), dict(trust._floors)
    with pytest.raises(TrustJournalDenied, match="capacity"):
        trust.publish(proposal(previous=heads["readback"]))
    assert rows(store) == before and trust._floors == floors
    trust.set_capacity(max_records=1, max_bytes=1, max_entry_bytes=1)
    reopened = SigningTrustJournal(store, controller_keys=pinned, minimum_revisions=floors)
    assert reopened.publish(heads["destination"])
    assert reopened.publish(heads["readback"])
    assert reopened.capacity()["used_bytes"] == sum(size(head) for head in heads.values())
    assert rows(store) == before


def test_worst_case_valid_unicode_envelope_fits_measured_default(journal):
    store, trust, proposal, _, _ = journal
    entries = [dict(key_id=chr(0x10000 + n) * 128, public_key_hex=public(Ed25519PrivateKey.generate()), state="active")
               for n in range(128)]
    envelope = proposal(entries=entries)
    assert size(envelope) > 200000
    assert size(envelope) <= DEFAULTS.max_entry_bytes
    trust.publish(envelope)
    assert trust.capacity()["used_bytes"] == size(envelope)
    assert json.loads(rows(store)[0]["envelope"]) == envelope


@pytest.mark.parametrize("boundary", ["entry", "aggregate"])
def test_exact_encoded_byte_boundary_and_growth_refusal(journal, boundary):
    store, trust, proposal, _, _ = journal
    first = proposal("destination")
    second = proposal("readback")
    total = size(first) + size(second)
    if boundary == "entry":
        trust.set_capacity(max_records=10, max_bytes=total, max_entry_bytes=size(first) - 1)
        with pytest.raises(TrustJournalDenied, match="capacity"):
            trust.publish(first)
        assert rows(store) == []
    trust.set_capacity(max_records=10, max_bytes=total, max_entry_bytes=size(first))
    trust.publish(first)
    trust.publish(second)
    assert trust.capacity()["used_bytes"] == total
    before = rows(store)
    with pytest.raises(TrustJournalDenied, match="capacity"):
        trust.publish(proposal("readback", second))
    assert rows(store) == before


def test_direct_old_writer_counts_actual_utf8_and_rolls_back_statement(journal):
    store, trust, proposal, _, path = journal
    entry = dict(key_id="\U00010000" * 128, public_key_hex=public(Ed25519PrivateKey.generate()), state="active")
    envelope = proposal(entries=[entry])
    encoded = json.dumps(envelope, sort_keys=True, ensure_ascii=False)
    actual = len(encoded.encode("utf-8"))
    assert actual > len(encoded)
    trust.set_capacity(max_records=1, max_bytes=actual, max_entry_bytes=actual)
    older = SqliteStore(path)
    try:
        older._db.execute("INSERT INTO signing_trust_revisions VALUES(?,?,?)", ("readback", 1, encoded))
        assert trust.capacity()["used_bytes"] == actual
        assert trust.publish(envelope)  # parsed idempotency does not require re-encoding old stored bytes
        with pytest.raises(sqlite3.IntegrityError, match="capacity"):
            older._db.execute("INSERT INTO signing_trust_revisions VALUES(?,?,?)", ("destination", 1, encoded))
        assert len(rows(store)) == 1
    finally:
        older.close()


def test_multirow_old_writer_is_all_or_nothing(journal):
    store, trust, proposal, _, _ = journal
    trust.set_capacity(max_records=1, max_bytes=10000, max_entry_bytes=10000)
    first, second = proposal("destination"), proposal("readback")
    with pytest.raises(sqlite3.IntegrityError, match="capacity"):
        store._db.execute("INSERT INTO signing_trust_revisions VALUES(?,?,?),(?,?,?)",
                          ("destination", 1, json.dumps(first), "readback", 1, json.dumps(second)))
    assert rows(store) == [] and trust.capacity()["used_records"] == 0


@pytest.mark.parametrize("command", [
    "UPDATE signing_trust_revisions SET envelope='{}'", "DELETE FROM signing_trust_revisions",
    "INSERT OR REPLACE INTO signing_trust_revisions SELECT * FROM signing_trust_revisions",
    "INSERT OR IGNORE INTO signing_trust_revisions SELECT * FROM signing_trust_revisions",
    "DELETE FROM " + TABLE, "INSERT OR REPLACE INTO " + TABLE + " SELECT * FROM " + TABLE,
    "UPDATE " + TABLE + " SET max_records=1.5", "UPDATE " + TABLE + " SET max_entry_bytes=1048577",
])
def test_ordinary_sql_cannot_erase_replace_or_malformed_policy(journal, command):
    store, trust, proposal, _, _ = journal
    trust.publish(proposal())
    before, policy = rows(store), trust.capacity()
    with pytest.raises(sqlite3.IntegrityError):
        store._db.execute(command)
    assert rows(store) == before and trust.capacity() == policy


def test_independent_domain_publishers_share_one_capacity(journal):
    store, trust, proposal, pinned, path = journal
    trust.set_capacity(max_records=3, max_bytes=10000, max_entry_bytes=10000)
    heads = {domain: proposal(domain) for domain in ("destination", "readback")}
    for head in heads.values():
        trust.publish(head)
    other = SqliteStore(path)
    second = SigningTrustJournal(other, controller_keys=pinned)

    def append(item):
        candidate, head = item
        try:
            candidate.publish(head)
            return True
        except TrustJournalDenied:
            return False

    try:
        candidates = [(trust, proposal("destination", heads["destination"])),
                      (second, proposal("readback", heads["readback"]))]
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(append, candidates)) == [False, True]
        assert len(rows(store)) == trust.capacity()["used_records"] == 3
    finally:
        other.close()


def test_policy_and_audit_compose_with_outer_rollback(journal):
    store, trust, _, _, _ = journal
    store._db.execute("CREATE TABLE policy_test_audit(message TEXT NOT NULL)")
    assert store._db.execute("SELECT count(*) AS n FROM " + TABLE).fetchone()["n"] == 0
    with pytest.raises(RuntimeError, match="outer abort"):
        with sql_atomic(store):
            trust.set_capacity(max_records=3, max_bytes=10000, max_entry_bytes=1000,
                               audit=lambda: store._db.execute("INSERT INTO policy_test_audit VALUES('changed')"))
            raise RuntimeError("outer abort")
    assert store._db.execute("SELECT count(*) AS n FROM " + TABLE).fetchone()["n"] == 0
    assert store._db.execute("SELECT count(*) AS n FROM policy_test_audit").fetchone()["n"] == 0
    before = trust.capacity()

    def failed_audit():
        store._db.execute("INSERT INTO policy_test_audit VALUES('aborted')")
        raise RuntimeError("audit abort")

    with pytest.raises(RuntimeError, match="audit abort"):
        trust.set_capacity(max_records=3, max_bytes=10000, max_entry_bytes=1000, audit=failed_audit)
    assert trust.capacity() == before
    assert store._db.execute("SELECT count(*) AS n FROM policy_test_audit").fetchone()["n"] == 0


def test_capacity_denied_revocation_is_not_a_revoked_key(journal):
    store, trust, proposal, _, _ = journal
    first = proposal()
    trust.publish(first)
    replacement = dict(key_id="replacement", public_key_hex=public(Ed25519PrivateKey.generate()), state="staged")
    head = proposal(previous=first, entries=first["keys"] + [replacement])
    trust.publish(head)
    trust.set_capacity(max_records=2, max_bytes=10000, max_entry_bytes=10000)
    revoked = [{**head["keys"][0], "state": "revoked"}, {**replacement, "state": "active"}]
    revocation = proposal(previous=head, entries=revoked)
    with pytest.raises(TrustJournalDenied, match="capacity"):
        trust.publish(revocation)
    with trust._transaction() as cur:
        persisted, registry = trust._load(cur, "readback")
    assert persisted == head and registry.resolve_active("old") == head["keys"][0]["public_key_hex"]
    trust.set_capacity(max_records=3, max_bytes=10000, max_entry_bytes=10000)
    trust.publish(revocation)
    with trust._transaction() as cur:
        persisted, registry = trust._load(cur, "readback")
    assert persisted == revocation
    with pytest.raises(ValueError, match="revoked"):
        registry.resolve_active("old")


@pytest.mark.parametrize("name", [TABLE, "signing_trust_revisions", "signing_trust_lock_v1", "tenant_store_binding"])
@pytest.mark.parametrize("spelling", [str.lower, str.upper, str.title], ids=["lower", "upper", "mixed"])
def test_reserved_temp_objects_refuse_bootstrap_publish_policy_and_snapshot(journal, name, spelling):
    store, trust, proposal, pinned, _ = journal
    store._db.execute("CREATE TEMP TABLE " + spelling(name) + "(fake INTEGER)")
    before_history = list(store._db.execute("SELECT * FROM main.signing_trust_revisions"))
    before_policy = list(store._db.execute("SELECT * FROM main." + TABLE))
    for call in (lambda: SigningTrustJournal(store, controller_keys=pinned), lambda: trust.publish(proposal()), trust.capacity,
                 lambda: verify_if_installed(store._db)):
        with pytest.raises(SigningJournalCapacityDenied, match="TEMP"):
            call()
        assert list(store._db.execute("SELECT * FROM main.signing_trust_revisions")) == before_history
        assert list(store._db.execute("SELECT * FROM main." + TABLE)) == before_policy
    assert store._db.execute("SELECT count(*) AS n FROM temp." + spelling(name)).fetchone()["n"] == 0


@pytest.mark.parametrize("damage", ["missing-trigger", "modified-trigger", "missing-policy", "missing-history"])
def test_partial_or_modified_installation_refuses_restart_and_snapshot(journal, damage):
    store, _, _, pinned, _ = journal
    if damage == "missing-trigger":
        store._db.execute("DROP TRIGGER signing_capacity_insert_v1")
    elif damage == "modified-trigger":
        store._db.execute("DROP TRIGGER signing_capacity_insert_v1")
        store._db.execute("CREATE TRIGGER signing_capacity_insert_v1 AFTER INSERT ON signing_trust_revisions BEGIN SELECT 1; END")
    elif damage == "missing-policy":
        store._db.execute("DROP TABLE " + TABLE)
    else:
        store._db.execute("DROP TABLE signing_trust_revisions")
    before = list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'"))
    with pytest.raises(SigningJournalCapacityDenied):
        SigningTrustJournal(store, controller_keys=pinned)
    with pytest.raises(SigningJournalCapacityDenied):
        verify_if_installed(store._db)
    assert list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'")) == before


def test_existing_sqlite_publication_does_not_claim_outer_transaction_composition(journal):
    store, trust, proposal, _, _ = journal
    with sql_atomic(store):
        with pytest.raises(sqlite3.OperationalError, match="within a transaction"):
            trust.publish(proposal())
        assert rows(store) == []


def test_selective_history_loss_is_not_reinitialized(journal):
    store, _, _, pinned, _ = journal
    for statement in _statements():
        store._db.execute("DROP TRIGGER " + statement.split()[5])
    store._db.execute("DROP TABLE signing_trust_revisions")
    with pytest.raises(SigningJournalCapacityDenied, match="history missing"):
        SigningTrustJournal(store, controller_keys=pinned)
    assert store._db.execute("SELECT 1 FROM sqlite_master WHERE name='signing_trust_revisions'").fetchone() is None


def test_initial_upgrade_preserves_valid_already_over_default_history(journal):
    store, _, proposal, pinned, _ = journal
    # Disposable complete old-version setup, before any managed capacity guard.
    for statement in _statements():
        store._db.execute("DROP TRIGGER " + statement.split()[5])
    store._db.execute("DROP TABLE " + TABLE)
    previous = None
    with sql_atomic(store):
        for _ in range(DEFAULTS.max_records + 1):
            previous = proposal(previous=previous)
            store._db.execute("INSERT INTO signing_trust_revisions VALUES(?,?,?)",
                              ("readback", previous["revision"], json.dumps(previous, sort_keys=True)))
    before = rows(store)
    upgraded = SigningTrustJournal(store, controller_keys=pinned)
    assert upgraded.publish(previous)
    with pytest.raises(TrustJournalDenied, match="capacity"):
        upgraded.publish(proposal(previous=previous))
    assert rows(store) == before
    assert upgraded.capacity()["used_records"] == DEFAULTS.max_records + 1


@pytest.mark.parametrize("damage", ["history-nullable", "history-extra-unique", "history-without-rowid",
                                  "policy-weaker-constraint", "policy-extra-column"])
def test_unsupported_preexisting_table_shape_is_not_repaired(journal, damage):
    store, _, _, pinned, _ = journal
    # Explicit disposable pre-upgrade schema, with all unit objects removed.
    for statement in _statements():
        store._db.execute("DROP TRIGGER " + statement.split()[5])
    store._db.execute("DROP TABLE " + TABLE)
    store._db.execute("DROP TABLE signing_trust_revisions")
    history = HISTORY_DDL
    policy = DDL
    if damage == "history-nullable":
        history = history.replace("domain TEXT NOT NULL", "domain TEXT")
    elif damage == "history-extra-unique":
        history = history.replace("PRIMARY KEY(domain, revision)", "PRIMARY KEY(domain, revision),UNIQUE(envelope)")
    elif damage == "history-without-rowid":
        history += " WITHOUT ROWID"
    elif damage == "policy-weaker-constraint":
        policy = policy.replace("max_records BETWEEN 1 AND 100000", "max_records BETWEEN 1 AND 100001")
    else:
        policy = policy[:-1] + ",extra INTEGER)"
    store._db.execute(history)
    # A policy-shaped unsupported legacy object must not be silently replaced.
    if damage.startswith("policy-"):
        store._db.execute(policy)
    before = list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'"))
    with pytest.raises(SigningJournalCapacityDenied, match="table constraints"):
        SigningTrustJournal(store, controller_keys=pinned)
    assert list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'")) == before


@pytest.mark.parametrize("name", [TABLE, "signing_trust_revisions"])
@pytest.mark.parametrize("spelling", [str.upper, str.title], ids=["upper", "mixed"])
def test_noncanonical_main_table_names_are_refused_without_repair(journal, name, spelling):
    store, _, _, pinned, _ = journal
    for statement in _statements():
        store._db.execute("DROP TRIGGER " + statement.split()[5])
    store._db.execute("DROP TABLE " + TABLE)
    store._db.execute("DROP TABLE signing_trust_revisions")
    store._db.execute(HISTORY_DDL.replace("signing_trust_revisions", spelling(name)) if name == "signing_trust_revisions" else HISTORY_DDL)
    if name == TABLE:
        store._db.execute(DDL.replace(TABLE, spelling(name)))
    before = list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'"))
    with pytest.raises(SigningJournalCapacityDenied, match="noncanonical signing journal table name"):
        SigningTrustJournal(store, controller_keys=pinned)
    assert list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'")) == before


@pytest.mark.parametrize("spelling", [str.upper, str.title], ids=["upper", "mixed"])
@pytest.mark.parametrize("installed_policy", [False, True])
def test_noncanonical_owned_trigger_name_is_refused_without_repair(journal, spelling, installed_policy):
    store, _, _, pinned, _ = journal
    if not installed_policy:
        for statement in _statements():
            store._db.execute("DROP TRIGGER " + statement.split()[5])
        store._db.execute("DROP TABLE " + TABLE)
    else:
        store._db.execute("DROP TRIGGER signing_capacity_insert_v1")
    store._db.execute("CREATE TRIGGER " + spelling("signing_capacity_insert_v1") +
                      " AFTER INSERT ON signing_trust_revisions BEGIN SELECT 1; END")
    before = list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'"))
    with pytest.raises(SigningJournalCapacityDenied, match="noncanonical signing journal capacity trigger name"):
        SigningTrustJournal(store, controller_keys=pinned)
    assert list(store._db.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'signing_%'")) == before
