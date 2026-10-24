"""Persistent legal holds and append-only signed audit checkpoint registry.

This is a durable control-plane building block, not external anchoring.
Never delete production audit history without an independently preserved and
reviewed checkpoint and an authorized retention transaction.
"""
import json

from .audit import AuditLog
from .store import PostgresStore, SqliteStore, sql_atomic


class AuditTrustError(ValueError):
    pass


class AuditTrustStore:
    def __init__(self, store):
        if not isinstance(store,(SqliteStore,PostgresStore)):
            raise AuditTrustError("durable SQL backend required")
        self.store=store
        from .checkpoint_capacity import (
            assert_postgres_namespace,
            assert_sqlite_namespace,
            install_postgres,
            install_sqlite,
        )
        with sql_atomic(store):
            c=store._db.cursor()
            try:
                if isinstance(store,PostgresStore):
                    assert_postgres_namespace(c)
                    # Bootstrap first, then the existing shared audit fence.
                    c.execute("SELECT pg_advisory_xact_lock(%s)",(911004,))
                    c.execute("SELECT pg_advisory_xact_lock(%s)",(911001,))
                    c.execute("CREATE TABLE IF NOT EXISTS audit_holds (name TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL)")
                    c.execute("CREATE TABLE IF NOT EXISTS audit_checkpoints (seq BIGINT PRIMARY KEY, data TEXT NOT NULL)")
                    install_postgres(c)
                else:
                    assert_sqlite_namespace(c)
                    c.execute("CREATE TABLE IF NOT EXISTS audit_holds (name TEXT PRIMARY KEY, enabled INTEGER NOT NULL)")
                    c.execute("CREATE TABLE IF NOT EXISTS audit_checkpoints (seq INTEGER PRIMARY KEY, data TEXT NOT NULL)")
                    install_sqlite(c)
                if getattr(store,"tenant_id",None):
                    from .tenant_store import _install_postgres_guards, _install_sqlite_guards
                    tables=("audit_holds","audit_checkpoints","checkpoint_capacity_policy_v1")
                    if isinstance(store,PostgresStore):
                        _install_postgres_guards(c,store.schema,tables)
                    else:
                        _install_sqlite_guards(c,tables)
            finally:
                c.close()

    def set_hold(self,name,enabled):
        if not isinstance(name,str) or not name:
            raise AuditTrustError("legal-hold identifier required")
        store=self.store
        if isinstance(store,SqliteStore):
            with store._lock:
                from .checkpoint_capacity import assert_sqlite_namespace
                assert_sqlite_namespace(store._db)
                store._db.execute("INSERT INTO audit_holds(name,enabled) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled",(name,int(bool(enabled))))
        else:
            with store._lock, store._db.transaction(), store._db.cursor() as c:
                from .checkpoint_capacity import assert_postgres_namespace
                assert_postgres_namespace(c)
                # Same transaction-scoped lock as PostgresStore.truncate_audit_before.
                c.execute("SELECT pg_advisory_xact_lock(%s)", (911003,))
                c.execute("INSERT INTO audit_holds(name,enabled) VALUES(%s,%s) ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled",(name,bool(enabled)))

    def holds(self):
        store=self.store
        if isinstance(store,SqliteStore):
            with store._lock:
                from .checkpoint_capacity import assert_sqlite_namespace
                assert_sqlite_namespace(store._db)
                rows=store._db.execute("SELECT name FROM audit_holds WHERE enabled=1 ORDER BY name").fetchall()
                return [r["name"] for r in rows]
        with store._lock,store._db.cursor() as c:
            from .checkpoint_capacity import assert_postgres_namespace
            assert_postgres_namespace(c)
            c.execute("SELECT name FROM audit_holds WHERE enabled=true ORDER BY name")
            return [r["name"] for r in c.fetchall()]

    def capacity(self):
        """Inspect durable retained audit payload limits and accounted usage."""
        from .audit_capacity import policy
        return policy(self.store)

    def set_capacity(self, *, max_records, max_bytes, max_entry_bytes, audit=None):
        """Trusted operator library configuration; never prunes existing rows."""
        from .audit_capacity import AuditLimits, policy
        return policy(self.store, limits=AuditLimits(max_records, max_bytes, max_entry_bytes), audit=audit)

    def checkpoint_capacity(self):
        """Inspect the separate checkpoint limits and actual stored UTF-8 usage."""
        from .checkpoint_capacity import policy
        return policy(self.store)

    def set_checkpoint_capacity(self, *, max_records, max_bytes, max_entry_bytes, audit=None):
        """Trusted library configuration; preserves every existing checkpoint."""
        from .checkpoint_capacity import CheckpointLimits, policy
        return policy(self.store,limits=CheckpointLimits(max_records,max_bytes,max_entry_bytes),audit=audit)

    def save_checkpoint(self,checkpoint,trusted_public_key_hex):
        if not isinstance(checkpoint,dict) or checkpoint.get("public_key_hex")!=trusted_public_key_hex:
            raise AuditTrustError("checkpoint signer not pinned")
        if not AuditLog.verify_checkpoint(checkpoint):
            raise AuditTrustError("checkpoint signature invalid")
        seq=checkpoint.get("seq")
        if not isinstance(seq,int) or seq<0:
            raise AuditTrustError("bad checkpoint sequence")
        store=self.store
        with sql_atomic(store):
            c=store._db.cursor()
            try:
                if isinstance(store,PostgresStore):
                    from .checkpoint_capacity import assert_postgres_namespace
                    assert_postgres_namespace(c)
                    c.execute("SELECT pg_advisory_xact_lock(%s)",(911001,))
                else:
                    from .checkpoint_capacity import assert_sqlite_namespace
                    assert_sqlite_namespace(c)
                records=store.load_audit()
                if not AuditLog.verify_chain(records,require_genesis=True):
                    raise AuditTrustError("stored audit chain failed verification")
                if seq>len(records):
                    raise AuditTrustError("checkpoint beyond current audit history")
                expected=(AuditLog.GENESIS if seq==0 else records[seq-1]["entry_hash"])
                if checkpoint.get("head_hash") != expected:
                    raise AuditTrustError("checkpoint signature does not match the stored audit history")
                blob=json.dumps(checkpoint,sort_keys=True)
                if isinstance(store,PostgresStore):
                    assert_postgres_namespace(c)
                else:
                    assert_sqlite_namespace(c)
                marker="%s" if isinstance(store,PostgresStore) else "?"
                c.execute("INSERT INTO audit_checkpoints(seq,data) VALUES("+marker+","+marker+")",(seq,blob))
            finally:
                c.close()
        return seq
