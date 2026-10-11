"""Persistent legal holds and append-only signed audit checkpoint registry.

This is a durable control-plane building block, not external anchoring.
Never delete production audit history without an independently preserved and
reviewed checkpoint and an authorized retention transaction.
"""
import json
import time
from .store import SqliteStore, PostgresStore
from .audit import AuditLog


class AuditTrustError(ValueError):
    pass


class AuditTrustStore:
    def __init__(self, store):
        if not isinstance(store,(SqliteStore,PostgresStore)):
            raise AuditTrustError("durable SQL backend required")
        self.store=store
        if isinstance(store,SqliteStore):
            with store._lock:
                store._db.execute("CREATE TABLE IF NOT EXISTS audit_holds (name TEXT PRIMARY KEY, enabled INTEGER NOT NULL)")
                store._db.execute("CREATE TABLE IF NOT EXISTS audit_checkpoints (seq INTEGER PRIMARY KEY, data TEXT NOT NULL)")
        else:
            with store._lock,store._db.cursor() as c:
                c.execute("CREATE TABLE IF NOT EXISTS audit_holds (name TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL)")
                c.execute("CREATE TABLE IF NOT EXISTS audit_checkpoints (seq BIGINT PRIMARY KEY, data TEXT NOT NULL)")

    def set_hold(self,name,enabled):
        if not isinstance(name,str) or not name:
            raise AuditTrustError("legal-hold identifier required")
        store=self.store
        if isinstance(store,SqliteStore):
            with store._lock:
                store._db.execute("INSERT INTO audit_holds(name,enabled) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled",(name,int(bool(enabled))))
        else:
            with store._lock,store._db.cursor() as c:
                c.execute("INSERT INTO audit_holds(name,enabled) VALUES(%s,%s) ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled",(name,bool(enabled)))

    def holds(self):
        store=self.store
        if isinstance(store,SqliteStore):
            with store._lock:
                rows=store._db.execute("SELECT name FROM audit_holds WHERE enabled=1 ORDER BY name").fetchall()
                return [r["name"] for r in rows]
        with store._lock,store._db.cursor() as c:
            c.execute("SELECT name FROM audit_holds WHERE enabled=true ORDER BY name")
            return [r["name"] for r in c.fetchall()]

    def save_checkpoint(self,checkpoint,trusted_public_key_hex):
        if not isinstance(checkpoint,dict) or checkpoint.get("public_key_hex")!=trusted_public_key_hex:
            raise AuditTrustError("checkpoint signer not pinned")
        if not AuditLog.verify_checkpoint(checkpoint):
            raise AuditTrustError("checkpoint signature invalid")
        seq=checkpoint.get("seq")
        if not isinstance(seq,int) or seq<0:
            raise AuditTrustError("bad checkpoint sequence")
        blob=json.dumps(checkpoint,sort_keys=True)
        store=self.store
        if isinstance(store,SqliteStore):
            with store._lock:
                store._db.execute("INSERT INTO audit_checkpoints(seq,data) VALUES(?,?)",(seq,blob))
        else:
            with store._lock,store._db.cursor() as c:
                c.execute("INSERT INTO audit_checkpoints(seq,data) VALUES(%s,%s)",(seq,blob))
        return seq
