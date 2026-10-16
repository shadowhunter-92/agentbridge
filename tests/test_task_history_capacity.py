"""Durable aggregate task history bounds do not delete terminal evidence."""

import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from src.governance.store import PostgresStore, sql_atomic
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle, LifecycleCapacity
from src.protocols.task_lifecycle import LifecycleRejected, TaskLifecycle
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_http import http_app as http_app
from tests.test_tenant_http import operator
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def task(identity):
    return TaskLifecycle(identity,"context","a2a")


def test_terminal_tasks_still_count_across_owners_and_restarts(network_sql_stores):
    first=DurableTaskLifecycle(network_sql_stores())
    first.set_history_capacity(2)
    for owner in ("one","two"):
        first.create(owner,task(owner))
        first.cancel(owner,owner,expected_sequence=0)
    second=DurableTaskLifecycle(network_sql_stores())
    assert second.history_capacity()=={"max_tasks":2,"used_tasks":2}
    with pytest.raises(LifecycleCapacity,match="historical-task"):
        second.create("third",task("third"))
    assert [t.sequence for t in first.events("one","one")]==[0,1]
    with pytest.raises(LifecycleCapacity,match="retained task history"):
        second.set_history_capacity(1)
    second.set_history_capacity(3)
    first.create("third",task("third"))
    assert first.history_capacity()["used_tasks"]==3


def test_concurrent_namespaces_share_one_history_cap(authority,namespaces):
    services=[DurableTaskLifecycle(namespaces("alpha")) for _ in range(2)]
    services[0].set_history_capacity(1)
    def create(index):
        try:
            services[index].create(str(index),task(str(index)))
            return True
        except LifecycleCapacity:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create,range(2)))==[False,True]
    assert services[1].history_capacity()=={"max_tasks":1,"used_tasks":1}
    beta=DurableTaskLifecycle(namespaces("beta"))
    assert beta.history_capacity()["used_tasks"]==0
    beta.create("third",task("third"))


def test_supported_older_task_insert_cannot_bypass_tenant_history_cap(authority,namespaces):
    store=namespaces("alpha")
    service=DurableTaskLifecycle(store)
    service.set_history_capacity(1)
    service.create("one",task("one"))
    # Same authenticated tenant store, but the old worker's SQL has no Python
    # history-cap check. Database enforcement must reject it independently.
    old=namespaces("alpha")
    with pytest.raises(Exception,match="historical-task capacity"):
        with sql_atomic(old):
            service._execute(old._db.cursor(),"INSERT INTO task_lifecycle_snapshots VALUES(?,?,?,0)",
                             ("other","other",service._encode(task("other"))))
    service.cancel("one","one",expected_sequence=0)
    assert len(service.events("one","one"))==2
    assert service.history_capacity()["used_tasks"]==1


@pytest.mark.parametrize("damage",["missing-row","unknown-version"])
def test_missing_policy_never_reinitializes_on_restart(network_sql_stores,damage):
    store=network_sql_stores()
    service=DurableTaskLifecycle(store)
    service.set_history_capacity(1)
    if damage=="missing-row":
        store._db.execute("DELETE FROM task_lifecycle_history_policy_v1")
    else:
        store._db.execute("UPDATE task_lifecycle_history_policy_v1 SET version=2")
    with pytest.raises(LifecycleCapacity,match="policy"):
        DurableTaskLifecycle(network_sql_stores())
    with pytest.raises(LifecycleCapacity,match="policy"):
        service.create("one",task("one"))


@pytest.mark.parametrize("table",["task_lifecycle_history_policy_v1","task_lifecycle_capacity_meta_v1"])
def test_history_policy_table_immediately_requires_tenant_scope(authority,namespaces,table):
    service=DurableTaskLifecycle(namespaces("alpha"))
    old=namespaces("alpha",legacy=True)
    with pytest.raises(Exception,match="tenant write scope|agentbridge_current_tenant"):
        old._db.execute("DELETE FROM "+table)
    assert service.history_capacity()["max_tasks"]==10000


@pytest.mark.parametrize("table",["task_lifecycle_history_policy_v1","task_lifecycle_capacity_meta_v1"])
def test_restart_rejects_partial_capacity_schema(network_sql_stores,table):
    store=network_sql_stores()
    service=DurableTaskLifecycle(store)
    service.set_history_capacity(1)
    store._db.execute("DROP TABLE "+table)
    with pytest.raises(LifecycleCapacity,match="capacity schema"):
        DurableTaskLifecycle(network_sql_stores())


def test_concurrent_older_raw_inserts_are_bounded_by_sql_trigger(authority,namespaces):
    service=DurableTaskLifecycle(namespaces("alpha"))
    service.set_history_capacity(1)
    stores=[namespaces("alpha") for _ in range(2)]
    def create(index):
        try:
            with sql_atomic(stores[index]):
                cur=stores[index]._db.cursor()
                try:
                    service._execute(cur,"INSERT INTO task_lifecycle_snapshots VALUES(?,?,?,0)",
                                     (str(index),str(index),service._encode(task(str(index)))))
                finally:
                    cur.close()
            return True
        except Exception as exc:
            assert "historical-task capacity" in str(exc)
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create,range(2)))==[False,True]
    assert service.history_capacity()["used_tasks"]==1


def test_old_postgres_writer_rechecks_capacity_after_real_blocker_commits(authority,namespaces):
    first=namespaces("alpha")
    if not isinstance(first,PostgresStore):
        pytest.skip("PostgreSQL trigger visibility after a real cross-connection wait")
    second=namespaces("alpha")
    service=DurableTaskLifecycle(first)
    service.set_history_capacity(1)
    def insert_second():
        with pytest.raises(Exception,match="historical-task capacity"):
            with sql_atomic(second):
                with second._db.cursor() as cur:
                    service._execute(cur,"INSERT INTO task_lifecycle_snapshots VALUES(?,?,?,0)",
                                     ("second","second",service._encode(task("second"))))
    future=None
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with sql_atomic(first):
                with first._db.cursor() as cur:
                    service._execute(cur,"INSERT INTO task_lifecycle_snapshots VALUES(?,?,?,0)",
                                     ("first","first",service._encode(task("first"))))
                    future=pool.submit(insert_second)
                    deadline=time.monotonic()+5
                    while not cur.execute("SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked",
                                          (first._db.info.backend_pid,second._db.info.backend_pid)).fetchone()["blocked"]:
                        if future.done():
                            future.result()
                            pytest.fail("second insert never waited on the actual trigger lock")
                        assert time.monotonic()<deadline,"SQL blocker not observed"
                        time.sleep(.01)
        finally:
            if future is not None:
                future.result(timeout=10)
    assert service.history_capacity()["used_tasks"]==1


def test_policy_audit_failure_and_outer_task_rollback_restore_capacity(tenant_app,monkeypatch):
    kernel,admins,*_=tenant_app
    service=kernel._runtimes["alpha"].tasks
    before=service.history_capacity()
    def fail(**kwargs):
        raise RuntimeError("abort capacity audit")
    monkeypatch.setattr(kernel._runtimes["alpha"].audit,"record",fail)
    with pytest.raises(RuntimeError,match="capacity audit"):
        admins["alpha"].set_task_history_capacity(1)
    assert service.history_capacity()==before
    with pytest.raises(RuntimeError,match="abort create"):
        with sql_atomic(service.store):
            service.create("one",task("one"))
            raise RuntimeError("abort create")
    assert service.history_capacity()==before


@pytest.mark.parametrize("limit",[True,0,-1,1000001,"1",None])
def test_invalid_capacity_rejected(network_sql_stores,limit):
    service=DurableTaskLifecycle(network_sql_stores())
    with pytest.raises(LifecycleRejected):
        service.set_history_capacity(limit)
    assert service.history_capacity()["max_tasks"]==10000


@pytest.mark.asyncio
async def test_operator_http_capacity_permissions_and_tenant_scope(tenant_app,http_app,loopback_server):
    directory,owner=tenant_app[4:]
    directory.enroll_member(owner,"alpha",ISSUER,"viewer",role="tenant_viewer")
    with loopback_server(lambda _:http_app) as (url,_):
        async with httpx.AsyncClient(base_url=url,trust_env=False) as client:
            endpoint="/v2/operator/task-history-capacity"
            assert (await client.put(endpoint,headers=operator(tenant_app,subject="viewer"),json={"max_tasks":1})).status_code==403
            assert (await client.put(endpoint,headers=operator(tenant_app),json={"max_tasks":1})).status_code==200
            assert (await client.get(endpoint,headers=operator(tenant_app))).json()["max_tasks"]==1
            assert (await client.get(endpoint,headers=operator(tenant_app,"beta"))).json()["max_tasks"]==10000
            assert (await client.put(endpoint,headers=operator(tenant_app),json={"max_tasks":True})).status_code==400
