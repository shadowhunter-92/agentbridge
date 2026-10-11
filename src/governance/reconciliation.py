"""Durable manual reconciliation for unknown agent operations.

An operator must provide an external reference and evidence digest. This module
does not assert the evidence is truthful; the reviewer is responsible for checking
the destination system independently.
"""
from __future__ import annotations
import hashlib
import json
import time
from .store import SqliteStore, PostgresStore
from .operation_ledger import OperationLedger, OperationConflict


class ReconciliationError(ValueError):
    pass


class Reconciliation:
    def __init__(self, store):
        self.store = store
        self.operations = OperationLedger(store)
        if isinstance(store, SqliteStore):
            with store._lock:
                store._db.execute(
                    "CREATE TABLE IF NOT EXISTS operation_reconciliations "
                    "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                    "result TEXT NOT NULL, external_reference TEXT NOT NULL, "
                    "evidence_sha256 TEXT NOT NULL, reviewer TEXT NOT NULL, "
                    "created REAL NOT NULL, PRIMARY KEY(agent_id, operation_id))")
        elif isinstance(store, PostgresStore):
            with store._lock, store._db.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS operation_reconciliations "
                    "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                    "result TEXT NOT NULL, external_reference TEXT NOT NULL, "
                    "evidence_sha256 TEXT NOT NULL, reviewer TEXT NOT NULL, "
                    "created DOUBLE PRECISION NOT NULL, PRIMARY KEY(agent_id, operation_id))")
        else:
            raise ReconciliationError("durable database required")

    def record(self, *, agent_id, operation_id, result, external_reference,
               evidence_sha256, reviewer):
        if result not in ("succeeded", "failed"):
            raise ReconciliationError("operator must determine succeeded or failed")
        if any(not isinstance(x, str) or not x.strip() or len(x)>512
               for x in (agent_id, operation_id, external_reference, reviewer)):
            raise ReconciliationError("missing reviewer or external reference")
        if (not isinstance(evidence_sha256,str) or len(evidence_sha256)!=64
                or any(c not in "0123456789abcdef" for c in evidence_sha256)):
            raise ReconciliationError("independent evidence SHA256 digest required")
        store=self.store
        if isinstance(store, SqliteStore):
            with store._lock:
                db=store._db
                db.execute("BEGIN IMMEDIATE")
                try:
                    row=db.execute("SELECT state FROM agent_operations WHERE agent_id=? AND operation_id=?",
                                   (agent_id,operation_id)).fetchone()
                    if not row or row["state"]!="unknown":
                        raise ReconciliationError("operation missing or no longer unknown")
                    db.execute("INSERT INTO operation_reconciliations VALUES(?,?,?,?,?,?,?)",
                               (agent_id,operation_id,result,external_reference,evidence_sha256,reviewer,time.time()))
                    db.execute("UPDATE agent_operations SET state=?,updated=? WHERE agent_id=? AND operation_id=?",
                               (result,time.time(),agent_id,operation_id))
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
        else:
            with store._lock, store._db.transaction(), store._db.cursor() as cur:
                cur.execute("SELECT state FROM agent_operations WHERE agent_id=%s AND operation_id=%s FOR UPDATE",
                            (agent_id,operation_id))
                row=cur.fetchone()
                if not row or row["state"]!="unknown":
                    raise ReconciliationError("operation missing or no longer unknown")
                cur.execute("INSERT INTO operation_reconciliations VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            (agent_id,operation_id,result,external_reference,evidence_sha256,reviewer,time.time()))
                cur.execute("UPDATE agent_operations SET state=%s,updated=%s WHERE agent_id=%s AND operation_id=%s",
                            (result,time.time(),agent_id,operation_id))
        return {"agent_id":agent_id,"operation_id":operation_id,"state":result,
                "evidence_sha256":evidence_sha256,"external_reference":external_reference,
                "reviewer":reviewer}
