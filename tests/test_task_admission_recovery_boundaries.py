"""Persistence boundaries, immutable allowance and link shape failures."""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest

from src.governance.authority import AuthorityDenied
from src.governance.gateway import GovernanceError
from src.governance.store import PostgresStore
from src.governance.task_admission import TaskAdmissionStore
from src.governance.task_intents import IntentLimits
from src.governance.tenant_kernel import principal_owner
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted
from tests.test_task_admission import admit, snapshot
from tests.test_task_admission_transactions import approved, fresh
from tests.test_task_intents import count
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def test_old_result_allowance_survives_lowered_new_submission_limit(queued_app):
    session, record, _, _ = accepted(queued_app)
    queued_app[1]["alpha"].set_task_intent_capacity(**asdict(replace(IntentLimits(), max_result_bytes=1)))
    receipt = admit(queued_app, session, record)
    assert receipt["result_limit_bytes"] == record["result_limit_bytes"] > 1
    assert session.task_intent("native-task") == record


@pytest.mark.parametrize("invalid", ["reservation", "snapshot", "record"])
def test_link_insert_rejects_mismatched_or_unbounded_metadata_atomically(queued_app, monkeypatch, invalid):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    original = runtime.task_admissions._insert
    before = snapshot(queued_app)

    def corrupt(metadata, task_snapshot):
        if invalid == "reservation":
            metadata = {**metadata, "reservation_token": "another-reservation"}
        elif invalid == "snapshot":
            task_snapshot += " "
        else:
            metadata = {**metadata, "unbounded": "a" * 8192}
        return original(metadata, task_snapshot)

    monkeypatch.setattr(runtime.task_admissions, "_insert", corrupt)
    with pytest.raises(Exception, match="invalid or unbounded"):
        admit(queued_app, session, record)
    assert snapshot(queued_app) == before
    assert session.task("native-task").state == TaskState.SUBMITTED


@pytest.mark.parametrize("extra", ["link", "meta", "standalone", "partial", "expression"])
def test_schema_qualification_rejects_additional_unique_restriction(namespaces, extra):
    store = namespaces("alpha")
    fields = [name + " " + typ + " NOT NULL" for name, typ in TaskAdmissionStore.COLUMNS]
    fields += ["PRIMARY KEY(owner_id,task_id)", "UNIQUE(agent_id,operation_id)"]
    if extra == "link":
        fields += ["UNIQUE(task_id)"]
    store._db.execute("CREATE TABLE task_operation_links_v1(" + ",".join(fields) + ")")
    store._db.execute("CREATE TABLE task_operation_links_meta_v1(singleton INTEGER NOT NULL PRIMARY KEY,"
                      "version INTEGER NOT NULL" + (" UNIQUE" if extra == "meta" else "") + ",schema_sha256 TEXT NOT NULL)")
    values = (1, 1, TaskAdmissionStore.SCHEMA_SHA256)
    store._db.execute("INSERT INTO task_operation_links_meta_v1 VALUES(" +
                      ("%s,%s,%s" if isinstance(store, PostgresStore) else "?,?,?") + ")", values)
    if extra in ("standalone", "partial", "expression"):
        key = "lower(agent_id)" if extra == "expression" else "agent_id"
        predicate = " WHERE event_sequence=1" if extra == "partial" else ""
        store._db.execute("CREATE UNIQUE INDEX unsupported_admission_restriction ON task_operation_links_v1(" +
                          key + ")" + predicate)
    with pytest.raises(AuthorityDenied, match="schema shape"):
        TaskAdmissionStore(store)


def test_independent_consumer_can_invalidate_earlier_grant_observation(queued_app, namespaces, authority, monkeypatch):
    runtime = queued_app[0]._runtimes["alpha"]
    if not isinstance(runtime.store, PostgresStore):
        pytest.skip("PostgreSQL MVCC observation/consumption race")
    session, record, approval = approved(queued_app)
    other = fresh(queued_app, namespaces, authority)[0]._runtimes["alpha"]
    scope = runtime.store.get_approval(approval)["capability"].split("|", 1)[1]
    before = snapshot(queued_app)
    observed, consumed = threading.Event(), threading.Event()
    original = runtime.approvals.is_granted

    def pause(*args):
        result = original(*args)
        assert result
        observed.set()
        assert consumed.wait(8)
        return result

    monkeypatch.setattr(runtime.approvals, "is_granted", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(admit, queued_app, session, record)
        try:
            assert observed.wait(5)
            assert other.approvals.consume("worker", "read", scope)
        finally:
            consumed.set()
        with pytest.raises(GovernanceError, match="already consumed"):
            pending.result(10)
    after = snapshot(queued_app)
    assert after["counts"] == before["counts"]
    assert after["budget"] == before["budget"]
    assert runtime.approvals.get(approval).status == "consumed"
    assert after["audit"]["decision"] == "deny"


@pytest.mark.parametrize("death", ["before_commit", "after_commit"])
def test_real_process_death_preserves_atomicity_and_committed_unknown_exposure(queued_app, tmp_path, death):
    session, record, approval = approved(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    before = snapshot(queued_app)

    def descriptor(store):
        if isinstance(store, PostgresStore):
            from psycopg.conninfo import make_conninfo
            return {"backend": "postgres", "schema": getattr(store, "schema", None),
                    "dsn": make_conninfo(store._db.info.dsn, password=store._db.info.password)}
        return {"backend": "sqlite", "path": store._db.execute("PRAGMA database_list").fetchone()["file"]}

    configuration = {"authority": descriptor(queued_app[4].store), "tenant": descriptor(runtime.store),
                     "verifiers": {issuer: asdict(verifier.config) for issuer, verifier in queued_app[4].verifiers.items()},
                     "death": death, "owner": principal_owner(session.principal), "task": "native-task",
                     "intent": record["intent_sha256"]}
    child = tmp_path / "admission_crash.py"
    child.write_text('''
import json, os
from src.api.auth_oidc import OidcConfig, OidcVerifier
from src.governance.authority import AuthorityDirectory
from src.governance.store import PostgresStore, SqliteStore
from src.governance.tenant_store import TenantPostgresStore, TenantSqliteStore
from src.governance.tenant_kernel import TenantKernel
from tests.test_task_intents import TARGETS
c = json.loads(os.environ["AGENTBRIDGE_CRASH_ADMISSION"])
a, t = c["authority"], c["tenant"]
authority = PostgresStore(a["dsn"]) if a["backend"] == "postgres" else SqliteStore(a["path"])
tenant = (TenantPostgresStore(t["dsn"], schema=t["schema"], tenant_id="alpha")
          if t["backend"] == "postgres" else TenantSqliteStore(t["path"], tenant_id="alpha"))
verifiers = {issuer: OidcVerifier(OidcConfig(**config)) for issuer, config in c["verifiers"].items()}
kernel = TenantKernel(AuthorityDirectory(authority, verifiers=verifiers), {"alpha": tenant}, costs={"alpha": {"read": 1, "write": 2}}, targets=TARGETS)
runtime = kernel._runtimes["alpha"]
if c["death"] == "before_commit":
    original = runtime.audit.record
    def die(**kwargs):
        original(**kwargs)
        os._exit(93)
    runtime.audit.record = die
kernel._admit_queued_intent("alpha", c["owner"], c["task"], c["intent"])
os._exit(94)
''', encoding="utf-8")
    environment = {**os.environ, "AGENTBRIDGE_CRASH_ADMISSION": json.dumps(configuration),
                   "PYTHONPATH": os.getcwd()}
    result = subprocess.run([sys.executable, str(child)], env=environment, capture_output=True, timeout=25)
    assert result.returncode == (93 if death == "before_commit" else 94), result.stderr.decode()
    if death == "before_commit":
        assert snapshot(queued_app) == before
        assert runtime.approvals.get(approval).status == "approved"
        assert session.task("native-task").state == TaskState.SUBMITTED
    else:
        receipt = queued_app[0]._queued_admission("alpha", configuration["owner"], "native-task", record["intent_sha256"])
        assert runtime.approvals.get(approval).status == "consumed"
        assert runtime.store.get_budget("worker")["reserved"] == {receipt["reservation_token"]: 1}
        assert runtime.operations.get("worker", receipt["operation_id"])["state"] == "unknown"
        assert count(runtime.store, "task_operation_links_v1") == 1
        after = snapshot(queued_app)
        with pytest.raises(AuthorityDenied):
            admit(queued_app, session, record)
        assert snapshot(queued_app) == after
