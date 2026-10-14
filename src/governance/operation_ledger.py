"""Crash-conservative SQL operation ledger for consequential agent actions.

Persist a request fingerprint before attempting effects. Once an operation is
claimed, a retry is rejected even if the worker crashes; an unknown result
requires external reconciliation by a trusted operator. This does NOT provide
exactly-once semantics at an arbitrary external destination.
"""
import json
import time

from .store import PostgresStore, SqliteStore


class OperationConflict(RuntimeError):
    pass


class OperationLedger:
    def __init__(self, store):
        if not isinstance(store, (SqliteStore, PostgresStore)):
            raise RuntimeError("operation ledger requires durable SQLite or PostgreSQL")
        self.store = store
        if isinstance(store, SqliteStore):
            with store._lock:
                store._db.execute(
                    "CREATE TABLE IF NOT EXISTS agent_operations "
                    "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                    "fingerprint TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL, "
                    "PRIMARY KEY(agent_id,operation_id))")
                store._db.execute("CREATE TABLE IF NOT EXISTS operation_reservations ("
                                  "agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                                  "token TEXT NOT NULL, PRIMARY KEY(agent_id, operation_id))")
        else:
            # CREATE TABLE IF NOT EXISTS races on pg_type catalog for concurrent
            # first-use workers. Serialize DDL on the same transaction advisory
            # lock used by PostgresStore schema bootstrap.
            with store._lock, store._db.transaction(), store._db.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS agent_operations "
                    "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                    "fingerprint TEXT NOT NULL, state TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL, "
                    "PRIMARY KEY(agent_id,operation_id))")
                cur.execute("CREATE TABLE IF NOT EXISTS operation_reservations ("
                            "agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                            "token TEXT NOT NULL, PRIMARY KEY(agent_id, operation_id))")

        if getattr(store, "tenant_id", None) is not None:
            if isinstance(store, SqliteStore):
                with store._lock:
                    store._db.execute("CREATE TABLE IF NOT EXISTS operation_authority ("
                                      "agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
                                      "binding TEXT NOT NULL,PRIMARY KEY(agent_id,operation_id))")
            else:
                with store._lock, store._db.transaction(), store._db.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (911004,))
                    cur.execute("CREATE TABLE IF NOT EXISTS operation_authority ("
                                "agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
                                "binding TEXT NOT NULL,PRIMARY KEY(agent_id,operation_id))")

    def claim(self, agent_id, operation_id, fingerprint, reservation_token=None, *, authority_binding=None):
        if not all(isinstance(x, str) and x and len(x) <= 256
                   for x in (agent_id, operation_id, fingerprint)):
            raise ValueError("invalid operation claim")
        if reservation_token is not None and (not isinstance(reservation_token, str) or not reservation_token):
            raise ValueError("reservation_token must be nonempty")
        binding = None
        if authority_binding is not None:
            if not isinstance(authority_binding, dict) or authority_binding.get("tenant_id") != getattr(self.store, "tenant_id", None) or authority_binding.get("agent_id") != agent_id:
                raise ValueError("operation authority does not match the bound tenant/agent")
            binding = json.dumps(authority_binding, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stamp = time.time()
        store = self.store
        if isinstance(store, SqliteStore):
            with store._lock:
                db = store._db
                db.execute("BEGIN IMMEDIATE")
                try:
                    row = db.execute(
                        "SELECT fingerprint,state FROM agent_operations "
                        "WHERE agent_id=? AND operation_id=?",
                        (agent_id, operation_id)).fetchone()
                    if row:
                        if row["fingerprint"] != fingerprint:
                            raise OperationConflict("idempotency key reused for different request")
                        raise OperationConflict("existing operation is " + row["state"] +
                                                "; no automatic replay")
                    db.execute(
                        "INSERT INTO agent_operations VALUES(?,?,?,?,?)",
                        (agent_id, operation_id, fingerprint, "unknown", stamp))
                    if reservation_token is not None:
                        db.execute("INSERT INTO operation_reservations VALUES(?,?,?)",
                                   (agent_id, operation_id, reservation_token))
                    if binding is not None:
                        db.execute("INSERT INTO operation_authority VALUES(?,?,?)", (agent_id, operation_id, binding))
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
            return
        with store._lock, store._db.transaction(), store._db.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"operation:{agent_id}:{operation_id}",))
            cur.execute(
                "SELECT fingerprint,state FROM agent_operations "
                "WHERE agent_id=%s AND operation_id=%s", (agent_id, operation_id))
            row = cur.fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    raise OperationConflict("idempotency key reused for different request")
                raise OperationConflict("existing operation is " + row["state"] +
                                        "; no automatic replay")
            cur.execute("INSERT INTO agent_operations VALUES(%s,%s,%s,%s,%s)",
                        (agent_id, operation_id, fingerprint, "unknown", stamp))
            if reservation_token is not None:
                cur.execute("INSERT INTO operation_reservations VALUES(%s,%s,%s)",
                            (agent_id, operation_id, reservation_token))

            if binding is not None:
                cur.execute("INSERT INTO operation_authority VALUES(%s,%s,%s)", (agent_id, operation_id, binding))

    def authority_binding(self, agent_id, operation_id):
        if getattr(self.store, "tenant_id", None) is None:
            return None
        with self.store._lock:
            if isinstance(self.store, SqliteStore):
                row = self.store._db.execute("SELECT binding FROM operation_authority WHERE agent_id=? AND operation_id=?", (agent_id, operation_id)).fetchone()
            else:
                with self.store._db.cursor() as cur:
                    cur.execute("SELECT binding FROM operation_authority WHERE agent_id=%s AND operation_id=%s", (agent_id, operation_id))
                    row = cur.fetchone()
        return json.loads(row["binding"]) if row else None

    def finish(self, agent_id, operation_id, state):
        if state not in ("succeeded", "failed", "unknown"):
            raise ValueError("invalid terminal operation state")
        store = self.store
        if isinstance(store, SqliteStore):
            with store._lock:
                cur = store._db.execute(
                    "UPDATE agent_operations SET state=?,updated=? "
                    "WHERE agent_id=? AND operation_id=?",
                    (state, time.time(), agent_id, operation_id))
                if cur.rowcount != 1:
                    raise OperationConflict("operation missing")
        else:
            with store._lock, store._db.cursor() as cur:
                cur.execute(
                    "UPDATE agent_operations SET state=%s,updated=%s "
                    "WHERE agent_id=%s AND operation_id=%s",
                    (state, time.time(), agent_id, operation_id))
                if cur.rowcount != 1:
                    raise OperationConflict("operation missing")

    def get(self, agent_id, operation_id):
        store = self.store
        if isinstance(store, SqliteStore):
            with store._lock:
                row = store._db.execute(
                    "SELECT fingerprint,state,updated FROM agent_operations "
                    "WHERE agent_id=? AND operation_id=?",
                    (agent_id, operation_id)).fetchone()
        else:
            with store._lock, store._db.cursor() as cur:
                cur.execute(
                    "SELECT fingerprint,state,updated FROM agent_operations "
                    "WHERE agent_id=%s AND operation_id=%s",
                    (agent_id, operation_id))
                row = cur.fetchone()
        return dict(row) if row else None
