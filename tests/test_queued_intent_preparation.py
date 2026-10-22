"""Restricted preparation derives current enrolled authority, never admission."""

import copy
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from src.governance.authority import AuthorityDenied, AuthorityDirectory, Principal
from src.governance.identity import AgentIdentity
from src.governance.policy_rules import DenyCapabilities, RequireApprovalAboveCost
from src.governance.store import PostgresStore
from src.governance.task_intents import IntentLimits
from src.governance.tenant_kernel import TenantKernel, principal_owner
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_task_intents import TARGETS, authenticated, count
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import human_grant
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def accepted(app, *, delegated=False):
    session, body, nonce = authenticated(app, delegation=human_grant(app) if delegated else None)
    record = session.submit_task(body, nonce=nonce)
    return session, record, body, nonce


def prepare(app, session, record):
    return app[0]._prepare_queued_intent(
        "alpha", principal_owner(session.principal), "native-task", record["intent_sha256"]
    )


def state(app):
    store = app[0]._runtimes["alpha"].store
    authority_store = app[4].store
    return {
        "budget": store.get_budget("worker"), "audit": store.load_audit_head(),
        "tables": {name: count(store, name) for name in (
            "task_intents_v1", "task_lifecycle_snapshots", "task_lifecycle_events", "agent_operations",
            "operation_reservations", "approvals",
        )},
        "replays": count(authority_store, "authority_replays"),
    }


@pytest.mark.parametrize("delegated", [False, True])
def test_preparation_is_guard_scoped_and_has_no_admission_or_accounting(queued_app, monkeypatch, delegated):
    queued_app[1]["alpha"].add_policy(RequireApprovalAboveCost(0))
    session, record, body, nonce = accepted(queued_app, delegated=delegated)
    runtime = queued_app[0]._runtimes["alpha"]
    before = state(queued_app)

    def prohibited(*args, **kwargs):
        raise AssertionError("preparation cannot authenticate, admit or execute")

    for component, method in (
        (runtime.policy, "authorize"), (runtime.budgets, "get"), (runtime.budgets, "reserve"),
        (runtime.budgets, "can_afford"), (runtime.approvals, "request"), (runtime.approvals, "consume"),
        (runtime.operations, "claim"), (runtime.gateway, "route_call"), (queued_app[4], "authenticate_agent"),
    ):
        monkeypatch.setattr(component, method, prohibited)
    monkeypatch.setattr("src.proxy.transport.invoke_target", prohibited)
    with prepare(queued_app, session, record) as prepared:
        assert queued_app[0]._assert_prepared_queued_intent(prepared) is prepared
        plan = prepared.plan
        assert plan["intent_sha256"] == record["intent_sha256"] and plan["execution_admitted"] is False
        assert plan["original_authorization_expires_at"] == record["provenance"]["authorization_expires_at"]
        assert plan["cost"] == 1 and plan["approval_required_now"] is True
        assert plan["result_limit_bytes"] == record["result_limit_bytes"]
        internal = prepared._authority.principal
        assert queued_app[4].assert_current(internal) is internal
        assert internal._proof and internal.request_body_sha256 == internal.request_nonce == ""
        assert internal.valid_until <= record["provenance"]["authorization_expires_at"]
        with pytest.raises(AuthorityDenied):
            queued_app[4].assert_request(internal, body=body, nonce=nonce)
        plan["wire"] = {"forged": True}
        assert prepared.plan["wire"] == json.loads(body)["wire"]
    with pytest.raises(AuthorityDenied, match="inactive"):
        queued_app[0]._assert_prepared_queued_intent(prepared)
    assert state(queued_app) == before


@pytest.mark.asyncio
async def test_internal_process_principal_cannot_enter_public_request_paths(queued_app):
    session, record, body, nonce = accepted(queued_app)
    with prepare(queued_app, session, record) as prepared:
        internal_session = queued_app[0].session(prepared._authority.principal)
        with pytest.raises(AuthorityDenied, match="different request"):
            internal_session.submit_task(body, nonce=nonce)
    with pytest.raises(AuthorityDenied, match="different request"):
        await internal_session.route(body, nonce=nonce)
    binding = copy.deepcopy(record["provenance"]["authority"])
    binding["capabilities"] = tuple(binding["capabilities"])
    binding["targets"] = tuple(binding["targets"])
    forged = Principal(**binding, valid_until=record["provenance"]["authorization_expires_at"])
    with pytest.raises(AuthorityDenied, match="unverified"):
        queued_app[4].assert_current(forged)


@pytest.mark.parametrize("delegated", [False, True])
def test_restart_derives_fresh_context_without_reauthenticating_old_nonce(queued_app, namespaces, authority, monkeypatch, delegated):
    session, record, _, _ = accepted(queued_app, delegated=delegated)
    with prepare(queued_app, session, record) as old:
        original_deadline = old.plan["original_authorization_expires_at"]
    directory = AuthorityDirectory(authority[3](), verifiers=authority[4])
    kernel = TenantKernel(directory, {t: namespaces(t) for t in ("alpha", "beta")},
                          costs=queued_app[0].costs, targets=TARGETS)
    monkeypatch.setattr(directory, "authenticate_agent", lambda *args, **kwargs: pytest.fail("old nonce reauthentication"))
    with kernel._prepare_queued_intent("alpha", principal_owner(session.principal), "native-task", record["intent_sha256"]) as fresh:
        assert fresh.plan["original_authorization_expires_at"] == original_deadline
        assert fresh._authority.principal.binding() == session.principal.binding()
        assert fresh._authority.principal._proof != old._authority.principal._proof
        with pytest.raises(AuthorityDenied):
            kernel._assert_prepared_queued_intent(old)
    assert count(kernel._runtimes["alpha"].store, "agent_operations") == 0


@pytest.mark.parametrize("change", ["tenant_revoked", "tenant_revision", "agent_revoked", "agent_revision", "agent_key", "agent_scope", "identity_key"])
def test_changed_or_revoked_machine_enrollment_prevents_preparation(queued_app, change):
    session, record, _, _ = accepted(queued_app)
    directory, owner = queued_app[4:]
    admin = queued_app[1]["alpha"]
    if change in ("tenant_revoked", "tenant_revision"):
        directory.set_tenant(owner, "alpha", active=change != "tenant_revoked")
    elif change == "agent_revoked":
        directory.revoke_agent(owner, "alpha", "worker")
    elif change == "identity_key":
        queued_app[0]._runtimes["alpha"].identities.register(AgentIdentity.generate("worker"))
    else:
        admin.enroll_agent("worker", AgentIdentity.generate("worker").public_key_hex if change == "agent_key"
                          else queued_app[2]["alpha"].public_key_hex,
                          capabilities=("read",) if change == "agent_scope" else ("read", "write"), targets=("ledger",))
    before = state(queued_app)
    with pytest.raises(AuthorityDenied):
        with prepare(queued_app, session, record):
            pytest.fail("changed enrollment prepared")
    assert state(queued_app) == before


@pytest.mark.parametrize("change", ["grant_revoked", "user_revoked", "user_revision", "grantor_revoked", "grantor_revision", "replacement_grant"])
def test_current_delegation_user_and_grantor_must_match_original(queued_app, change):
    session, record, _, _ = accepted(queued_app, delegated=True)
    directory, owner = queued_app[4:]
    if change in ("grant_revoked", "replacement_grant"):
        directory.revoke_delegation(owner, "alpha", session.principal.delegation_id)
        if change == "replacement_grant":
            replacement = human_grant(queued_app)
            renewed, _, _ = authenticated(queued_app, delegation=replacement)
            assert renewed.task_intent("native-task") == record
    elif change in ("user_revoked", "grantor_revoked"):
        directory.revoke_member(owner, "alpha", ISSUER, "human" if change == "user_revoked" else "administrator")
    else:
        subject = "human" if change == "user_revision" else "administrator"
        directory.enroll_member(owner, "alpha", ISSUER, subject,
                                role="tenant_operator" if subject == "human" else "tenant_admin",
                                capabilities=("read",), targets=("ledger",))
    before = state(queued_app)
    with pytest.raises(AuthorityDenied):
        with prepare(queued_app, session, record):
            pytest.fail("stale delegated intent prepared")
    assert state(queued_app) == before


@pytest.mark.parametrize("delegated", [False, True])
@pytest.mark.parametrize("offset", [0, 1])
def test_original_expiry_is_strict_even_after_restart_or_observation(queued_app, monkeypatch, delegated, offset):
    session, record, _, _ = accepted(queued_app, delegated=delegated)
    deadline = record["provenance"]["authorization_expires_at"]
    monkeypatch.setattr("src.governance.queued_intent_preparation.time.time", lambda: deadline + offset)
    with pytest.raises(AuthorityDenied):
        with prepare(queued_app, session, record):
            pytest.fail("expired intent prepared")


def test_live_preparation_rechecks_expiry_and_cannot_be_reused_after_guard(queued_app, monkeypatch):
    session, record, _, _ = accepted(queued_app)
    with prepare(queued_app, session, record) as prepared:
        monkeypatch.setattr("src.governance.queued_intent_preparation.time.time", lambda: prepared._authority.original_deadline)
        with pytest.raises(AuthorityDenied):
            queued_app[0]._assert_prepared_queued_intent(prepared)


def test_preparation_scope_cannot_be_transferred_or_reactivated(queued_app):
    session, record, _, _ = accepted(queued_app)
    kernel = queued_app[0]
    with prepare(queued_app, session, record) as prepared:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(kernel._assert_prepared_queued_intent, prepared)
            with pytest.raises(AuthorityDenied, match="inactive"):
                result.result(timeout=5)
        # A new lease identity cannot reuse the original HMAC proof.
        forged = replace(prepared._authority, _lease=object())
        with pytest.raises(AuthorityDenied):
            queued_app[4]._assert_queued_intent(forged, kernel._runtimes["alpha"].task_intents)
        with prepare(queued_app, session, record) as nested:
            assert kernel._assert_prepared_queued_intent(nested) is nested
        with pytest.raises(AuthorityDenied):
            kernel._assert_prepared_queued_intent(nested)
        assert kernel._assert_prepared_queued_intent(prepared) is prepared
    with prepare(queued_app, session, record) as fresh:
        assert kernel._assert_prepared_queued_intent(fresh) is fresh
        with pytest.raises(AuthorityDenied, match="inactive"):
            kernel._assert_prepared_queued_intent(replace(prepared))
    assert not hasattr(queued_app[4]._transaction_context, "queued_intent_guards")


def test_short_original_delegation_deadline_cannot_be_renewed(queued_app, monkeypatch):
    directory = queued_app[4]
    user = directory.authenticate_operator(ISSUER, queued_app[3]("human", tenant="alpha"), tenant_id="alpha")
    grant = directory.grant_delegation(
        queued_app[1]["alpha"].principal, user, "worker", capabilities=("read",), targets=("ledger",),
        expires_at=time.time() + 60,
    )
    session, body, nonce = authenticated(queued_app, delegation=grant)
    record = session.submit_task(body, nonce=nonce)
    deadline = record["provenance"]["authorization_expires_at"]
    assert deadline < float(nonce.split(":", 1)[0]) + 300
    with prepare(queued_app, session, record) as prepared:
        assert prepared._authority.original_deadline == deadline
    monkeypatch.setattr("src.governance.queued_intent_preparation.time.time", lambda: deadline)
    with pytest.raises(AuthorityDenied):
        with prepare(queued_app, session, record):
            pytest.fail("original short delegation deadline was renewed")


def test_short_process_context_expiry_requires_fresh_preparation(queued_app, monkeypatch):
    session, record, _, _ = accepted(queued_app)
    before = state(queued_app)
    with prepare(queued_app, session, record) as prepared:
        deadline = prepared._authority.principal.valid_until
        original = prepared._authority.original_deadline
        assert deadline < original
        monkeypatch.setattr("src.governance.queued_intent_preparation.time.time", lambda: deadline)
        with pytest.raises(AuthorityDenied):
            queued_app[0]._assert_prepared_queued_intent(prepared)
        with prepare(queued_app, session, record) as fresh:
            assert fresh._authority.principal.valid_until > deadline
            assert fresh._authority.original_deadline == original
            assert fresh.plan["execution_admitted"] is False
            with pytest.raises(AuthorityDenied):
                queued_app[0]._assert_prepared_queued_intent(prepared)
    assert state(queued_app) == before


@pytest.mark.parametrize("namespace", ["authority", "tenant"])
@pytest.mark.parametrize("isolation", ["repeatable read", "serializable"])
def test_unsupported_postgres_isolation_prevents_preparation(queued_app, namespace, isolation):
    session, record, _, _ = accepted(queued_app)
    store = queued_app[4].store if namespace == "authority" else queued_app[0]._runtimes["alpha"].store
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL isolation only")
    before = state(queued_app)
    store._db.execute("SELECT set_config('default_transaction_isolation', %s, false)", (isolation,))
    try:
        with pytest.raises(AuthorityDenied, match="READ COMMITTED"):
            with prepare(queued_app, session, record):
                pass
    finally:
        store._db.execute("SET default_transaction_isolation='read committed'")
    assert state(queued_app) == before


def test_live_preparation_rechecks_tenant_postgres_isolation(queued_app):
    session, record, _, _ = accepted(queued_app)
    store = queued_app[0]._runtimes["alpha"].store
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL isolation only")
    before = state(queued_app)
    with prepare(queued_app, session, record) as prepared:
        store._db.execute("SET default_transaction_isolation='repeatable read'")
        try:
            with pytest.raises(AuthorityDenied, match="READ COMMITTED"):
                queued_app[0]._assert_prepared_queued_intent(prepared)
        finally:
            store._db.execute("SET default_transaction_isolation='read committed'")
    assert state(queued_app) == before


@pytest.mark.parametrize("change", ["cost", "target", "policy", "production"])
def test_current_operator_configuration_and_policy_are_revalidated(queued_app, monkeypatch, change):
    session, record, _, _ = accepted(queued_app)
    costs = copy.deepcopy({t: dict(values) for t, values in queued_app[0].costs.items()})
    targets = copy.deepcopy(TARGETS)
    if change == "cost":
        costs["alpha"]["read"] = 2
    elif change == "target":
        targets["alpha"]["ledger"]["command"] = "changed-never-run"
    elif change == "policy":
        queued_app[1]["alpha"].add_policy(DenyCapabilities(["read"]))
    else:
        monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    kernel = TenantKernel(queued_app[4], {t: r.store for t, r in queued_app[0]._runtimes.items()}, costs=costs, targets=targets)
    before = state(queued_app)
    with pytest.raises(AuthorityDenied):
        with kernel._prepare_queued_intent("alpha", principal_owner(session.principal), "native-task", record["intent_sha256"]):
            pytest.fail("changed configuration prepared")
    assert state(queued_app) == before


def poison_row(monkeypatch, intents, mutate, *, recompute=True):
    original = intents._execute
    replacement_digest = []

    def execute(query, values=()):
        result = original(query, values)
        if query.startswith("SELECT i.*"):
            row = dict(result.fetchone())
            record = json.loads(row["record"])
            mutate(row, record)
            row["record"] = json.dumps(record, sort_keys=True, separators=(",", ":"))
            if recompute:
                row["fingerprint"] = hashlib.sha256(row["record"].encode()).hexdigest()
            return SimpleNamespace(fetchone=lambda: row)
        return result

    # Obtain the expected corrupted digest without mutating durable SQL history.
    row = dict(original("SELECT * FROM task_intents_v1").fetchone())
    record = json.loads(row["record"])
    mutate(row, record)
    replacement_digest.append(hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                              if recompute else row["fingerprint"])
    monkeypatch.setattr(intents, "_execute", execute)
    return replacement_digest[0]


@pytest.mark.parametrize("corruption", ["digest", "body_digest", "body", "tenant", "owner_scope", "agent_column", "operation_column", "allowance", "deadline", "signer", "capability", "cost_type", "snapshot"])
def test_corrupted_retained_record_cannot_become_prepared_authority(queued_app, monkeypatch, corruption):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]

    def mutate(row, value):
        provenance = value["provenance"]
        if corruption == "digest":
            value["accepted_at"] += 1
        elif corruption == "body_digest":
            provenance["request_body_sha256"] = "0" * 64
        elif corruption == "body":
            provenance["request_body"] += " "
        elif corruption == "tenant":
            provenance["authority"]["tenant_id"] = "beta"
        elif corruption == "owner_scope":
            provenance["authority"]["capabilities"] = ["read"]
        elif corruption == "agent_column":
            row["agent_id"] = "other-worker"
        elif corruption == "operation_column":
            row["operation_id"] = "other-operation-123456"
        elif corruption == "allowance":
            row["result_limit_bytes"] = 0
        elif corruption == "deadline":
            provenance["authorization_expires_at"] += 300
        elif corruption == "signer":
            provenance["signer_public_key_hex"] = "0" * 64
        elif corruption == "capability":
            provenance["capability"] = "write"
        elif corruption == "cost_type":
            provenance["operator_cost"] = "1"
        else:
            row["initial_snapshot"] = None

    expected = poison_row(monkeypatch, runtime.task_intents, mutate, recompute=corruption != "digest")
    before = state(queued_app)
    with pytest.raises(AuthorityDenied):
        with queued_app[0]._prepare_queued_intent("alpha", principal_owner(session.principal), "native-task", expected):
            pytest.fail("corrupted retained record prepared")
    assert state(queued_app) == before


def test_exact_owner_task_and_digest_and_nonqueued_status_are_required(queued_app):
    session, record, _, _ = accepted(queued_app)
    for tenant, owner, task, digest in (
        ("beta", principal_owner(session.principal), "native-task", record["intent_sha256"]),
        ("alpha", "different-owner", "native-task", record["intent_sha256"]),
        ("alpha", principal_owner(session.principal), "missing-task", record["intent_sha256"]),
        ("alpha", principal_owner(session.principal), "native-task", "0" * 64),
    ):
        with pytest.raises(AuthorityDenied):
            with queued_app[0]._prepare_queued_intent(tenant, owner, task, digest):
                pytest.fail("wrong intent reference prepared")
    with prepare(queued_app, session, record) as prepared:
        queued_app[0]._runtimes["alpha"].tasks.cancel(principal_owner(session.principal), "native-task", expected_sequence=0)
        with pytest.raises(AuthorityDenied):
            queued_app[0]._assert_prepared_queued_intent(prepared)


def test_prepared_object_seals_and_original_allowance_are_preserved(queued_app):
    session, record, _, _ = accepted(queued_app)
    queued_app[1]["alpha"].set_task_intent_capacity(**asdict(replace(IntentLimits(), max_result_bytes=1)))
    with prepare(queued_app, session, record) as prepared:
        assert prepared.plan["result_limit_bytes"] == record["result_limit_bytes"]
        for forged in (prepared.plan, replace(prepared, plan_json="{}"), replace(prepared, tenant_id="beta"),
                       replace(prepared, _proof=b"0" * 32)):
            with pytest.raises(AuthorityDenied):
                queued_app[0]._assert_prepared_queued_intent(forged)
