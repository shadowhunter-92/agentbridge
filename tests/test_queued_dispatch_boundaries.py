"""Current authority, transactional settlement and explicit cancellation bounds."""
import asyncio
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.api.trusted_targets import SecurityConfigurationError
from src.governance.authority import AuthorityDenied
from src.governance.operation_ledger import OperationConflict
from src.governance.operator_review import UntrustedReviewer, canonical_review_payload
from src.governance.policy_rules import DenyCapabilities
from src.governance.reconciliation import Reconciliation, ReconciliationError
from src.governance.signing_trust_journal import SigningTrustJournal
from src.governance.store import sql_atomic
from src.governance.task_intents import IntentLimits
from src.protocols.task_lifecycle import TaskState
from tests.test_queued_dispatch_execution import (
    _admit,
    _assert_success,
    _assert_unknown,
    _effects,
    _public,
    _rows,
)
from tests.test_queued_dispatch_execution import dispatch_app as dispatch_app


@pytest.mark.parametrize("stage", ["budget", "ledger", "event", "snapshot", "audit"])
def test_after_effect_local_participant_failure_rolls_back_then_readback_settles(dispatch_app, monkeypatch, stage):
    app = dispatch_app
    task = _admit(app)
    if stage in ("event", "snapshot"):
        original = app.runtime.tasks._execute
        marker = "INSERT INTO task_lifecycle_events" if stage == "event" else "UPDATE task_lifecycle_snapshots"
        def failure(cur, query, values):
            result = original(cur, query, values)
            if query.startswith(marker):
                raise RuntimeError("after local " + stage)
            return result
        component, method = app.runtime.tasks, "_execute"
    elif stage == "audit":
        component, method = app.runtime.audit, "record"
        original = component.record
        def failure(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get("action") == "task.verified-execution":
                raise RuntimeError("after local audit")
            return result
    else:
        component, method = (app.runtime.budgets, "commit") if stage == "budget" else (app.runtime.operations, "finish")
        original = getattr(component, method)
        def failure(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("after local " + stage)
    monkeypatch.setattr(component, method, failure)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    _assert_unknown(app, task, effects=1)
    assert app.runtime.tasks.events(task.refs[1], task.refs[2]) == task.initial_events
    assert not any(row["action"] == "task.verified-execution" for row in app.runtime.store.load_audit())
    monkeypatch.setattr(component, method, original)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("settlement retry cannot send"))
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)


@pytest.mark.parametrize("change", ["revoked", "policy", "cost", "target", "new-approval"])
def test_current_changes_deny_before_attempt_and_do_not_release_admission(dispatch_app, monkeypatch, change):
    app = dispatch_app
    task = _admit(app)
    if change == "revoked":
        app.admin.revoke_agent("worker")
    elif change == "policy":
        app.admin.add_policy(DenyCapabilities(["write"]))
    elif change == "cost":
        app.kernel.costs = MappingProxyType({"alpha": MappingProxyType({"write": 3})})
    elif change == "target":
        config = dict(app.kernel._target_env["alpha"])
        targets = json.loads(config["AGENTBRIDGE_TARGETS_JSON"])
        targets["ledger"]["destination_id"] = "changed"
        config["AGENTBRIDGE_TARGETS_JSON"] = json.dumps(targets)
        app.kernel._target_env = {"alpha": config}
    else:
        app.admin.mark_sensitive("write")
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("denied dispatch sent"))
    with pytest.raises((AuthorityDenied, SecurityConfigurationError)):
        app.kernel._dispatch_queued_once(*task.refs)
    assert _effects(app) == []
    assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
    assert app.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}


def test_dispatch_inside_uncommitted_outer_transaction_cannot_send(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("uncommitted marker sent"))
    with sql_atomic(app.runtime.store):
        with pytest.raises(AuthorityDenied, match="own durable transaction"):
            app.kernel._dispatch_queued_once(*task.refs)
    assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
    assert _effects(app) == []


def test_legacy_terminal_history_is_preserved_with_separate_verified_outcome(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    original = app.adapter.observe
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("readback temporarily unavailable")))
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    app.runtime.tasks.cancel(task.refs[1], task.refs[2], expected_sequence=1)
    terminal_history = app.runtime.tasks.events(task.refs[1], task.refs[2])
    monkeypatch.setattr(app.adapter, "observe", original)
    result = app.kernel._recover_queued(*task.refs)
    assert result["state"] == "succeeded"
    assert result["result"]["previous_terminal_state"] == "canceled"
    assert app.runtime.tasks.events(task.refs[1], task.refs[2]) == terminal_history
    assert app.runtime.store.get_budget("worker")["spent"] == 2
    assert app.runtime.operations.get("worker", task.operation_id)["state"] == "succeeded"


def test_post_attempt_cancel_is_bounded_idempotent_request_and_no_refund(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: (_ for _ in ()).throw(TimeoutError("zero effect uncertain")))
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    for reason in ("", "x" * 201, "\U0001f680" * 51, None):
        with pytest.raises(ValueError):
            app.kernel._cancel_queued(*task.refs, reason=reason)
    assert app.kernel._cancel_queued(*task.refs, reason="\U0001f680" * 50)["state"] == "unknown"
    before = app.runtime.store.load_audit_head()
    assert app.kernel._cancel_queued(*task.refs, reason="second request")["state"] == "unknown"
    assert before == app.runtime.store.load_audit_head()
    assert len(_rows(app.config["tenant_path"], "task_execution_controls_v1")) == 1
    assert app.runtime.tasks.events(task.refs[1], task.refs[2]) == task.initial_events
    _assert_unknown(app, task, effects=0)


def test_original_allowance_survives_lower_operator_default_and_unicode_ids(dispatch_app):
    app = dispatch_app
    task = _admit(app, task_id="\U0001f9ed" * 128, context_id="\U0001f30c" * 128, operation_id="\U0001f680" * 128)
    app.admin.set_task_intent_capacity(**asdict(replace(IntentLimits(), max_result_bytes=1)))
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)
    assert task.accepted["result_limit_bytes"] == 65536


def test_recovery_after_authorization_expiry_never_renews_execution(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    original = app.adapter.observe
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("withheld")))
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    authorization = app.runtime.task_executions.decision(task.refs[1], task.refs[2])["authorization"]
    # Only the process clock for verification is advanced; destination history
    # is unchanged and the new RO observation is freshly signed at this time.
    real = time.time
    monkeypatch.setattr(time, "time", lambda: max(real(), authorization["expires_at"] + 301))
    monkeypatch.setattr(app.adapter, "observe", original)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("expired authority cannot send"))
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)


def test_task_manual_digest_fallback_is_denied_and_signed_review_is_required(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    original = app.adapter.observe
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("withheld")))
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    with pytest.raises(ReconciliationError, match="task-aware"):
        Reconciliation(app.runtime.store).record(agent_id="worker", operation_id=task.operation_id, result="succeeded",
            external_reference="manual", evidence_sha256="a" * 64, reviewer="a name")
    monkeypatch.setattr(app.adapter, "observe", original)
    prepared = app.kernel._prepare_queued_reconciliation(app.admin, *task.refs[1:])
    with pytest.raises(UntrustedReviewer):
        app.kernel._reconcile_queued(app.admin, prepared["completion"], reviewer="reviewer", reviewer_signature_hex=None)
    _assert_unknown(app, task, effects=1)
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON", json.dumps({"reviewer": _public(key)}))
    statement = {"reviewer": "reviewer", **prepared["review_material"]}
    signature = key.sign(canonical_review_payload(statement)).hex()
    assert app.kernel._reconcile_queued(app.admin, prepared["completion"], reviewer="reviewer", reviewer_signature_hex=signature)["state"] == "succeeded"
    _assert_success(app, task)


def test_sealed_readback_cannot_be_forged_cross_kernel_or_mutated(dispatch_app, monkeypatch):
    from src.governance.queued_task_dispatch import _finish_verified
    app = dispatch_app
    task = _admit(app)
    original = app.adapter.observe
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("withheld")))
    app.kernel._dispatch_queued_once(*task.refs)
    monkeypatch.setattr(app.adapter, "observe", original)
    prepared = app.kernel._prepare_queued_reconciliation(app.admin, *task.refs[1:])["completion"]
    for forged in (copy.copy({}), replace(prepared, evidence_json="{}"), replace(prepared, proof=b"x" * 32)):
        with pytest.raises(AuthorityDenied):
            _finish_verified(app.kernel, forged)
    _assert_unknown(app, task, effects=1)


@pytest.mark.parametrize("part", ["result", "destination_receipt", "readback_attestation"])
def test_mismatched_readback_never_refunds_or_settles(dispatch_app, monkeypatch, part):
    app = dispatch_app
    task = _admit(app)
    original = app.adapter.observe
    def mismatched(*args):
        values = list(original(*args))
        index = ("result", "destination_receipt", "readback_attestation").index(part)
        values[index] = {**values[index], "forged": True}
        return tuple(values)
    monkeypatch.setattr(app.adapter, "observe", mismatched)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    _assert_unknown(app, task, effects=1)
    monkeypatch.setattr(app.adapter, "observe", original)
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"


def test_authority_expiring_while_waiting_for_fence_never_commits_marker(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    acquire, real = app.adapter.acquire, time.time
    def waited(*args):
        acquired = acquire(*args)
        monkeypatch.setattr(time, "time", lambda: real() + 301)
        return acquired
    monkeypatch.setattr(app.adapter, "acquire", waited)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("expired attempt sent"))
    with pytest.raises(AuthorityDenied):
        app.kernel._dispatch_queued_once(*task.refs)
    assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
    assert _effects(app) == []
    assert app.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}


def test_synchronous_claim_cannot_collide_with_queued_admission_or_invoke(dispatch_app):
    app = dispatch_app
    task = _admit(app)
    provenance = task.accepted["provenance"]
    async def forbidden(_wire):
        pytest.fail("colliding public operation invoked")
    with pytest.raises(OperationConflict):
        asyncio.run(app.runtime.gateway.route_call(agent_id="worker", src_proto="mcp", dst_proto="mcp",
            src_wire=task.accepted["submission"]["wire"], invoke=forbidden, cost=2, target_id="ledger",
            operation_id=task.operation_id, signed_body=provenance["request_body"].encode(),
            signed_nonce=provenance["request_nonce"], principal=task.session.principal))
    assert app.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}
    assert _effects(app) == []
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"


def test_public_route_rejects_queued_only_descriptor_before_any_effect(dispatch_app):
    app = dispatch_app
    task = _admit(app)
    provenance = task.accepted["provenance"]
    before = app.runtime.store.get_budget("worker")
    with pytest.raises(SecurityConfigurationError):
        asyncio.run(task.session.route(provenance["request_body"].encode(), nonce=provenance["request_nonce"]))
    assert _effects(app) == []
    assert app.runtime.store.get_budget("worker") == before


def test_production_rejects_queued_configuration_and_private_execution(dispatch_app, monkeypatch):
    from tests.test_queued_dispatch_execution import _open
    app = dispatch_app
    task = _admit(app)
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    with pytest.raises(AuthorityDenied, match="nonproduction"):
        _open(app.config)
    app.kernel.environment = "production"
    for method in (app.kernel._dispatch_queued_once, app.kernel._recover_queued, app.kernel._queued_execution):
        with pytest.raises(AuthorityDenied, match="nonproduction"):
            method(*task.refs)
    assert _effects(app) == []


@pytest.mark.parametrize("rotate", [False, True])
def test_current_signing_journal_is_checked_after_execution_guard_exits(dispatch_app, monkeypatch, rotate):
    from examples.qualify_trust_evidence import signed_registry
    app = dispatch_app
    controllers = {domain: Ed25519PrivateKey.generate() for domain in ("destination", "readback")}
    journal = SigningTrustJournal(app.runtime.store, controller_keys={domain: _public(key) for domain, key in controllers.items()})
    envelopes = {}
    for domain, role in (("destination", "destination"), ("readback", "observer")):
        envelopes[domain] = signed_registry(controllers[domain], domain, 1, None, [{
            "key_id": app.config["descriptor"][role + "_key_id"],
            "public_key_hex": app.config["descriptor"][role + "_public_key_hex"], "state": "active"}])
        journal.publish(envelopes[domain])
    app.adapter.trust_journal = journal
    task = _admit(app)
    check = journal.settlement_keys
    def outside_guard(*args, **kwargs):
        assert not getattr(app.directory._transaction_context, "queued_intent_guards", ())
        return check(*args, **kwargs)
    monkeypatch.setattr(journal, "settlement_keys", outside_guard)
    if rotate:
        original = app.adapter.observe
        monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("withheld until rotation")))
        assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
        old = dict(envelopes["readback"]["keys"][0])
        replacement = {"key_id": "replacement", "public_key_hex": _public(Ed25519PrivateKey.generate()), "state": "staged"}
        staged = signed_registry(controllers["readback"], "readback", 2, envelopes["readback"], [old, replacement])
        journal.publish(staged)
        old["state"], replacement["state"] = "revoked", "active"
        journal.publish(signed_registry(controllers["readback"], "readback", 3, staged, [old, replacement]))
        monkeypatch.setattr(app.adapter, "observe", original)
        assert app.kernel._recover_queued(*task.refs)["state"] == "unknown"
        _assert_unknown(app, task, effects=1)
    else:
        assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
        _assert_success(app, task)
        assert app.runtime.task_executions.result(task.refs[1], task.refs[2])["trust_context"]["readback_revision"] == 1


def test_lowered_budget_and_quota_limits_preserve_existing_held_admission(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    with pytest.raises(ValueError, match="outstanding exposure"):
        app.admin.set_budget("worker", spend_limit=1)
    app.admin.set_budget("worker", spend_limit=2, rate_limit=1)
    from src.governance.admission_quotas import QuotaLimits
    lowered = replace(QuotaLimits(), enabled=True, spend_limit=0, user_spend_limit=0,
                      max_active=1, user_max_active=1)
    app.admin.set_quotas(**asdict(lowered))
    def prohibited(*args, **kwargs):
        pytest.fail("existing held admission was charged or quota-admitted again")
    monkeypatch.setattr(app.runtime.gateway._quotas, "admit", prohibited)
    monkeypatch.setattr(app.runtime.budgets, "can_afford", prohibited)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)


@pytest.mark.parametrize("boundary", ["before-marker", "after-marker"])
def test_independent_connection_cancellation_race_has_one_durable_decision(dispatch_app, monkeypatch, boundary):
    from tests.test_queued_dispatch_execution import _close, _open
    app = dispatch_app
    task = _admit(app)
    other = _open(app.config)
    entered, release = threading.Event(), threading.Event()
    method = "acquire" if boundary == "before-marker" else "commit"
    original = getattr(app.adapter, method)
    def gated(*args):
        entered.set()
        assert release.wait(timeout=4)
        return original(*args)
    monkeypatch.setattr(app.adapter, method, gated)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            worker = executor.submit(app.kernel._dispatch_queued_once, *task.refs)
            assert entered.wait(timeout=4)
            canceled = executor.submit(other.kernel._cancel_queued, *task.refs, reason="coordinated cancellation")
            cancellation = canceled.result(timeout=4)
            release.set()
            dispatched = worker.result(timeout=8)
        if boundary == "before-marker":
            assert cancellation["state"] == dispatched["state"] == "closed"
            assert _effects(app) == []
            assert app.runtime.tasks.get(task.refs[1], task.refs[2]).state == TaskState.CANCELED
            assert app.runtime.store.get_budget("worker")["reserved"] == {}
        else:
            assert cancellation["state"] == "unknown" and dispatched["state"] == "succeeded"
            assert app.runtime.task_executions.cancellation(task.refs[1], task.refs[2])["kind"] == "cancel-request"
            _assert_success(app, task)
    finally:
        release.set()
        _close(other)


def test_verified_settlement_joins_outer_rollback_without_replaying_effect(dispatch_app, monkeypatch):
    from src.governance.queued_task_dispatch import _finish_verified
    app = dispatch_app
    task = _admit(app)
    observe = app.adapter.observe
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("withheld")))
    app.kernel._dispatch_queued_once(*task.refs)
    monkeypatch.setattr(app.adapter, "observe", observe)
    completion = app.kernel._prepare_queued_reconciliation(app.admin, *task.refs[1:])["completion"]
    with pytest.raises(RuntimeError, match="outer rollback"):
        with sql_atomic(app.runtime.store):
            assert _finish_verified(app.kernel, completion)["state"] == "succeeded"
            raise RuntimeError("outer rollback")
    _assert_unknown(app, task, effects=1)
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)


def test_actual_sql_audit_capacity_after_effect_preserves_readback_recovery(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    capacity = app.runtime.audit_trust
    original = app.adapter.observe
    saved = {}
    def saturate_after_observation(*args):
        observed = original(*args)
        current = capacity.capacity()
        saved.update(current)
        assert current["used_records"] > 0
        capacity.set_capacity(max_records=current["used_records"], max_bytes=current["max_bytes"],
                              max_entry_bytes=current["max_entry_bytes"])
        return observed
    monkeypatch.setattr(app.adapter, "observe", saturate_after_observation)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    _assert_unknown(app, task, effects=1)
    assert app.runtime.tasks.events(task.refs[1], task.refs[2]) == task.initial_events
    capacity.set_capacity(max_records=saved["max_records"], max_bytes=saved["max_bytes"],
                          max_entry_bytes=saved["max_entry_bytes"])
    monkeypatch.setattr(app.adapter, "observe", original)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("capacity recovery cannot resend"))
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)
