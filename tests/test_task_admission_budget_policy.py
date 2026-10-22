"""Private queued work requires existing operator budget policy before defaults."""

import pytest

from src.governance.gateway import GovernanceError
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted
from tests.test_task_admission import admit, snapshot
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


@pytest.mark.parametrize("policy", [{}, {"spent": 0}, {"spend_limit": 10, "rate_limit": 100},
                                  {"spend_limit": 10, "window_seconds": 60}])
def test_empty_or_incomplete_operator_budget_policy_cannot_seed_defaults(queued_app, monkeypatch, policy):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    runtime.store.upsert_budget("worker", policy)
    before = snapshot(queued_app)
    checks = []
    original = runtime.budgets.can_afford

    def observe(*args, **kwargs):
        checks.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime.budgets, "can_afford", observe)
    with pytest.raises(GovernanceError, match="operator budget"):
        admit(queued_app, session, record)
    assert not checks
    after = snapshot(queued_app)
    assert after["budget"] == before["budget"] == policy
    assert after["counts"] == before["counts"]
    assert after["audit"]["decision"] == "deny"


def test_existing_operator_policy_allows_normal_bookkeeping_defaults(queued_app):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    runtime.store.upsert_budget("worker", {"spend_limit": 10, "rate_limit": 100, "window_seconds": 60})
    receipt = admit(queued_app, session, record)
    budget = runtime.store.get_budget("worker")
    assert budget["spent"] == 0 and budget["calls"] == []
    assert budget["reserved"] == {receipt["reservation_token"]: 1}
