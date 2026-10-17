"""Durable tenant/human caps include existing exposure and atomic rollback."""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import httpx
import pytest

from src.governance.admission_quotas import AdmissionQuotas, QuotaDenied, QuotaLimits, quota_owner
from src.governance.authority import Principal, sign_tenant_request
from src.governance.budget import Budget, BudgetManager
from src.governance.gateway import GovernanceError
from src.governance.identity import AgentIdentity
from src.governance.operation_ledger import OperationLedger
from src.governance.reconciliation import Reconciliation
from src.governance.store import sql_atomic
from src.governance.tenant_kernel import TenantKernel
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_http import http_app as http_app
from tests.test_tenant_http import operator
from tests.test_tenant_kernel import human_grant, signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def operation():
    return "quota-operation-" + uuid.uuid4().hex


@pytest.mark.asyncio
async def test_tenant_cap_and_restart_preserve_total_spend(tenant_app):
    kernel, admins, _, _, directory, _ = tenant_app
    admins["alpha"].set_quotas(enabled=True, spend_limit=1)
    session, body, nonce = signed_session(tenant_app, operation=operation())
    await session.route(body, nonce=nonce)
    again = TenantKernel(directory, {t: r.store for t, r in kernel._runtimes.items()}, costs=kernel.costs)
    admin = again.session(admins["alpha"].principal)
    assert admin.get_quotas()["limits"]["spend_limit"] == 1
    denied, body, nonce = signed_session(tenant_app, operation=operation())
    with pytest.raises(GovernanceError, match="tenant spend quota"):
        await again.session(denied.principal).route(body, nonce=nonce)
    assert admins["alpha"].get_budget("worker")["spent"] == 1
    other, body, nonce = signed_session(tenant_app, "beta", operation=operation())
    await other.route(body, nonce=nonce)


@pytest.mark.asyncio
async def test_human_limit_survives_new_grants_but_isolates_other_human(tenant_app):
    tenant_app[1]["alpha"].set_quotas(enabled=True, user_spend_limit=1)
    first, body, nonce = signed_session(tenant_app, delegation=human_grant(tenant_app), operation=operation())
    await first.route(body, nonce=nonce)
    renewed, body, nonce = signed_session(tenant_app, delegation=human_grant(tenant_app), operation=operation())
    assert quota_owner(first.principal) == quota_owner(renewed.principal)
    with pytest.raises(GovernanceError, match="user spend quota"):
        await renewed.route(body, nonce=nonce)
    other, body, nonce = signed_session(tenant_app, delegation=human_grant(tenant_app, "other"), operation=operation())
    await other.route(body, nonce=nonce)
    assert tenant_app[1]["alpha"].get_budget("worker")["spent"] == 2


@pytest.mark.asyncio
async def test_human_limit_is_shared_across_delegated_agents(tenant_app):
    kernel, admins, _, token, directory, _ = tenant_app
    admins["alpha"].set_quotas(enabled=True, user_spend_limit=1)
    first, body, nonce = signed_session(tenant_app, delegation=human_grant(tenant_app), operation=operation())
    await first.route(body, nonce=nonce)
    second = AgentIdentity.generate("other-worker")
    admins["alpha"].enroll_agent(second.agent_id, second.public_key_hex, capabilities=("read",), targets=("ledger",))
    admins["alpha"].set_budget(second.agent_id, spend_limit=10)
    user = directory.authenticate_operator(ISSUER, token("human", tenant="alpha"), tenant_id="alpha")
    grant = directory.grant_delegation(
        admins["alpha"].principal,
        user,
        second.agent_id,
        capabilities=("read",),
        targets=("ledger",),
        expires_at=time.time() + 600,
    )
    body = json.dumps(
        {
            "src": "mcp",
            "dst": "mcp",
            "operation_id": operation(),
            "wire": {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
        }
    ).encode()
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    principal = directory.authenticate_agent(
        "alpha",
        second.agent_id,
        nonce,
        body,
        sign_tenant_request(second, "alpha", nonce, body, delegation_id=grant),
        delegation_id=grant,
    )
    with pytest.raises(GovernanceError, match="user spend quota"):
        await kernel.session(principal).route(body, nonce=nonce)
    assert admins["alpha"].get_budget(second.agent_id)["reserved"] == {}


@pytest.mark.asyncio
async def test_unknown_exposure_remains_until_reconciliation(tenant_app):
    kernel, admins, _, _, _, _ = tenant_app
    admins["alpha"].set_quotas(enabled=True, max_active=1, user_max_active=1)
    session, body, nonce = signed_session(tenant_app, operation=operation())
    runtime = kernel._runtimes["alpha"]
    request = json.loads(body)

    async def lost_ack(wire):
        raise ConnectionError("destination outcome unavailable")

    with pytest.raises(ConnectionError):
        await runtime.gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            src_wire=request["wire"],
            invoke=lost_ack,
            cost=1,
            operation_id=request["operation_id"],
            signed_body=body,
            signed_nonce=nonce,
            principal=session.principal,
        )
    second, body, nonce = signed_session(tenant_app, operation=operation())
    with pytest.raises(GovernanceError, match="active operations quota"):
        await second.route(body, nonce=nonce)
    assert runtime.budgets.get("worker").reserved == 1
    Reconciliation(runtime.store).record(
        agent_id="worker",
        operation_id=request["operation_id"],
        result="failed",
        external_reference="synthetic-no-effect",
        evidence_sha256="a" * 64,
        reviewer="local-test-operator",
    )
    third, body, nonce = signed_session(tenant_app, operation=operation())
    await third.route(body, nonce=nonce)
    assert runtime.budgets.get("worker").spent == 1 and runtime.budgets.get("worker").reserved == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limits,reason",
    [
        ({"rate_limit": 1}, "tenant rate"),
        ({"user_rate_limit": 1}, "user rate"),
        ({"max_records": 1}, "history capacity"),
    ],
)
async def test_rate_and_history_capacity_fail_closed(tenant_app, limits, reason):
    tenant_app[1]["alpha"].set_quotas(enabled=True, **limits)
    first, body, nonce = signed_session(tenant_app, operation=operation())
    await first.route(body, nonce=nonce)
    second, body, nonce = signed_session(tenant_app, operation=operation())
    with pytest.raises(GovernanceError, match=reason):
        await second.route(body, nonce=nonce)
    assert tenant_app[1]["alpha"].get_budget("worker")["spent"] == 1


def test_policy_change_and_audit_are_atomic(tenant_app, monkeypatch):
    runtime = tenant_app[0]._runtimes["alpha"]
    before = tenant_app[1]["alpha"].get_quotas()

    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(runtime.audit, "record", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        tenant_app[1]["alpha"].set_quotas(enabled=True, spend_limit=0)
    assert tenant_app[1]["alpha"].get_quotas() == before


@pytest.mark.asyncio
async def test_unattributed_legacy_exposure_is_not_reset(tenant_app):
    runtime = tenant_app[0]._runtimes["alpha"]
    legacy_token, _ = runtime.budgets.reserve("worker", 3)
    assert runtime.budgets.commit("worker", legacy_token)
    tenant_app[1]["alpha"].set_quotas(enabled=True, user_spend_limit=3)
    session, body, nonce = signed_session(tenant_app, delegation=human_grant(tenant_app), operation=operation())
    with pytest.raises(GovernanceError, match="user spend quota"):
        await session.route(body, nonce=nonce)
    usage = tenant_app[1]["alpha"].get_quotas()["usage"]
    assert usage["unattributed_spend"] == 3 and usage["spend"] == 3


def test_enabled_database_guard_rejects_old_worker_claim(tenant_app, namespaces):
    tenant_app[1]["alpha"].set_quotas(enabled=True)
    old_worker = namespaces("alpha")
    with pytest.raises(Exception, match="atomic quota admission required"):
        OperationLedger(old_worker).claim("worker", operation(), "old-worker-no-quota")


def test_independent_connections_cannot_over_admit(tenant_app, namespaces):
    tenant_app[1]["alpha"].set_quotas(enabled=True, spend_limit=1)
    stores = [namespaces("alpha"), namespaces("alpha")]
    managers = [AdmissionQuotas(store) for store in stores]
    ledgers = [OperationLedger(store) for store in stores]
    gate = Barrier(2)

    def run(index):
        store, manager, ledger = stores[index], managers[index], ledgers[index]
        agent, op = "race-" + str(index), operation()
        budgets = BudgetManager(store)
        budgets.set_budget(agent, Budget(spend_limit=10))
        principal = Principal("alpha", agent, "urn:agentbridge:enrollment", "machine", 1, agent_id=agent)
        gate.wait(timeout=5)
        try:
            with sql_atomic(store):
                ledger.claim(
                    agent, op, "same-cost", before_insert=lambda: manager.admit(principal, agent, op, "same-cost", 1)
                )
                token, _ = budgets.reserve(agent, 1)
                ledger.attach_reservation(agent, op, token)
            return True
        except QuotaDenied:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(results) == [False, True]
    assert tenant_app[1]["alpha"].get_quotas()["usage"]["spend"] == 1


@pytest.mark.parametrize(
    "values",
    [
        {"spend_limit": True},
        {"user_spend_limit": "1"},
        {"spend_limit": float("nan")},
        {"max_active": 0},
        {"rate_limit": True},
        {"enabled": 1},
    ],
)
def test_invalid_policy_does_not_silently_default(values):
    with pytest.raises(ValueError):
        QuotaLimits(**values).validated()


@pytest.mark.asyncio
async def test_http_policy_permissions_validation_and_tenant_isolation(tenant_app, http_app):
    directory, owner = tenant_app[4:]
    directory.enroll_member(owner, "alpha", ISSUER, "viewer", role="tenant_viewer")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app), base_url="http://local") as client:
        response = await client.put(
            "/v2/operator/quotas", headers=operator(tenant_app, subject="viewer"), json={"enabled": True}
        )
        assert response.status_code == 403
        assert (
            await client.put(
                "/v2/operator/quotas", headers=operator(tenant_app), json={"enabled": True, "spend_limit": 1.0}
            )
        ).status_code == 200
        assert (await client.get("/v2/operator/quotas", headers=operator(tenant_app))).json()["limits"]["enabled"]
        assert not (await client.get("/v2/operator/quotas", headers=operator(tenant_app, "beta"))).json()["limits"][
            "enabled"
        ]
        assert (
            await client.put("/v2/operator/quotas", headers=operator(tenant_app), json={"enabled": "yes"})
        ).status_code == 400


def test_quota_owner_does_not_change_with_scope_or_agent_for_same_human():
    first = Principal(
        "alpha", "human", "https://issuer.example", "delegated_human", 1, agent_id="one", capabilities=("read", "write")
    )
    assert quota_owner(first) == quota_owner(
        replace(first, agent_id="two", capabilities=("read",), delegation_id="renewed")
    )
    assert quota_owner(first) != quota_owner(replace(first, subject="other"))
    assert quota_owner(first) != quota_owner(replace(first, tenant_id="beta"))


@pytest.mark.asyncio
async def test_altered_policy_cannot_leave_a_cached_gateway_without_quotas(tenant_app):
    kernel, admins, _, _, directory, _ = tenant_app
    admins["alpha"].set_quotas(enabled=True)
    store = kernel._runtimes["alpha"].store
    store._db.execute("UPDATE admission_quota_policy_v1 SET policy='{}' WHERE singleton=1")
    gateway = kernel._runtimes["alpha"].gateway
    gateway._operations, gateway._quotas = None, None
    for _ in range(2):
        with pytest.raises(QuotaDenied, match="altered or unsupported"):
            gateway._operation_ledger()
        assert gateway._operations is None
    with pytest.raises(QuotaDenied, match="altered or unsupported"):
        TenantKernel(directory, {t: r.store for t, r in kernel._runtimes.items()}, costs=kernel.costs)
    assert kernel._runtimes["alpha"].budgets.get("worker").reserved == 0
    with pytest.raises(Exception, match="atomic quota admission required"):
        OperationLedger(store).claim("worker", operation(), "old-worker-no-quota")


@pytest.mark.asyncio
async def test_approval_failure_rolls_back_quota_capacity(tenant_app, monkeypatch):
    kernel, admins, _, _, _, _ = tenant_app
    admins["alpha"].set_quotas(enabled=True, rate_limit=1, max_records=1)
    admins["alpha"].mark_sensitive("read")
    op = operation()
    first, body, nonce = signed_session(tenant_app, operation=op)
    with pytest.raises(GovernanceError) as denied:
        await first.route(body, nonce=nonce)
    assert admins["alpha"].approve(denied.value.approval_id)
    runtime = kernel._runtimes["alpha"]
    original = runtime.approvals.consume

    def fail(*args, **kwargs):
        assert original(*args, **kwargs)
        raise RuntimeError("failure after approval consumption")

    monkeypatch.setattr(runtime.approvals, "consume", fail)
    second, body, nonce = signed_session(tenant_app, operation=op)
    with pytest.raises(RuntimeError, match="after approval"):
        await second.route(body, nonce=nonce)
    assert admins["alpha"].get_quotas()["usage"]["records"] == 0
    assert runtime.approvals.get(denied.value.approval_id).status == "approved"
    monkeypatch.setattr(runtime.approvals, "consume", original)
    third, body, nonce = signed_session(tenant_app, operation=op)
    await third.route(body, nonce=nonce)
    assert admins["alpha"].get_quotas()["usage"]["records"] == 1


@pytest.mark.parametrize("stage", ["quota-record", "reservation"])
def test_actual_process_death_rolls_back_quota_record(tenant_app, tmp_path, stage):
    import os
    import subprocess
    import sys

    from src.governance.store import SqliteStore

    kernel, admins, _, _, _, _ = tenant_app
    admins["alpha"].set_quotas(enabled=True, max_records=1)
    store = kernel._runtimes["alpha"].store
    op = operation()
    if isinstance(store, SqliteStore):
        config = {"backend": "sqlite", "path": str(store.path)}
    else:
        from psycopg.conninfo import make_conninfo

        config = {
            "backend": "postgres",
            "dsn": make_conninfo(store._db.info.dsn, password=store._db.info.password),
            "schema": store.schema,
        }
    config.update(operation=op, stage=stage)
    child = tmp_path / "quota_crash.py"
    child.write_text(
        """
import json,os
from src.governance.admission_quotas import AdmissionQuotas
from src.governance.authority import Principal
from src.governance.operation_ledger import OperationLedger
from src.governance.budget import BudgetManager
from src.governance.store import sql_atomic
from src.governance.tenant_store import TenantSqliteStore,TenantPostgresStore
c=json.loads(os.environ['AGENTBRIDGE_QUOTA_CRASH'])
s=TenantSqliteStore(c['path'],tenant_id='alpha') if c['backend']=='sqlite' else TenantPostgresStore(c['dsn'],schema=c['schema'],tenant_id='alpha')
ledger=OperationLedger(s); quotas=AdmissionQuotas(s); budgets=BudgetManager(s)
principal=Principal('alpha','worker','urn:agentbridge:enrollment','machine',1,agent_id='worker')
with sql_atomic(s):
    def quota():
        quotas.admit(principal,'worker',c['operation'],'crash-fingerprint',1)
        if c['stage']=='quota-record': os._exit(93)
    ledger.claim('worker',c['operation'],'crash-fingerprint',before_insert=quota)
    token,_=budgets.reserve('worker',1)
    ledger.attach_reservation('worker',c['operation'],token)
    os._exit(93)
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(AGENTBRIDGE_QUOTA_CRASH=json.dumps(config), PYTHONPATH=os.getcwd())
    result = subprocess.run([sys.executable, str(child)], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 93, result.stderr
    assert kernel._runtimes["alpha"].operations.get("worker", op) is None
    assert kernel._runtimes["alpha"].budgets.get("worker").reserved == 0
    assert admins["alpha"].get_quotas()["usage"]["records"] == 0


@pytest.mark.asyncio
async def test_lowered_limit_preserves_usage_and_does_not_reset_capacity(tenant_app):
    admin = tenant_app[1]["alpha"]
    admin.set_quotas(enabled=True, spend_limit=10)
    first, body, nonce = signed_session(tenant_app, operation=operation())
    await first.route(body, nonce=nonce)
    admin.set_quotas(enabled=True, spend_limit=0)
    assert admin.get_quotas()["usage"]["spend"] == 1
    second, body, nonce = signed_session(tenant_app, operation=operation())
    with pytest.raises(GovernanceError, match="tenant spend quota"):
        await second.route(body, nonce=nonce)


def test_unknown_policy_version_blocks_old_worker_even_when_caps_were_disabled(tenant_app):
    store = tenant_app[0]._runtimes["alpha"].store
    store._db.execute("UPDATE admission_quota_policy_v1 SET version=2 WHERE singleton=1")
    with pytest.raises(Exception, match="atomic quota admission required"):
        OperationLedger(store).claim("worker", operation(), "old-worker-unknown-version")


def test_quota_callback_cannot_create_orphan_records_outside_a_claim_transaction(tenant_app):
    runtime = tenant_app[0]._runtimes["alpha"]
    principal = Principal("alpha", "worker", "urn:agentbridge:enrollment", "machine", 1, agent_id="worker")
    with pytest.raises(RuntimeError, match="operation claim transaction"):
        runtime.gateway._quotas.admit(principal, "worker", operation(), "orphan-attempt", 1)
    assert tenant_app[1]["alpha"].get_quotas()["usage"]["records"] == 0


@pytest.mark.parametrize("damage", ["missing-policy-row", "missing-record-table"])
def test_quota_restart_rejects_incomplete_persisted_state(tenant_app, damage):
    runtime = tenant_app[0]._runtimes["alpha"]
    tenant_app[1]["alpha"].set_quotas(enabled=True, spend_limit=1)
    if damage == "missing-policy-row":
        runtime.store._db.execute("DELETE FROM admission_quota_policy_v1")
    else:
        runtime.store._db.execute("DROP TABLE admission_quota_records_v1")
    with pytest.raises(QuotaDenied, match="missing|incomplete"):
        AdmissionQuotas(runtime.store)


def test_quota_constructor_guards_new_tables_without_a_kernel_seal(authority, namespaces):
    store = namespaces("alpha")
    OperationLedger(store)
    manager = AdmissionQuotas(store)
    old = namespaces("alpha", legacy=True)
    with pytest.raises(Exception, match="tenant write scope|agentbridge_current_tenant"):
        old._db.execute("UPDATE admission_quota_policy_v1 SET policy='{}' WHERE singleton=1")
    assert not manager.inspect()["limits"]["enabled"]
