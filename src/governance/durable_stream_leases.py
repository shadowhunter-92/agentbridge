"""Shared authorized stream allocations; never a physical TCP connection cap.

One operator-owned authority database coordinates the entire configured fleet.
Expired allocations cannot renew. Each send rechecks authority and its lease;
a paused process may still hold an old TCP socket, requiring frontdoor limits.
"""
from __future__ import annotations

import json
import math
import secrets
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from .admission_quotas import quota_owner
from .authority import AuthorityDenied
from .store import PostgresStore, sql_atomic


class StreamCapacity(ValueError):
    pass


@dataclass(frozen=True)
class FleetStreamLimits:
    max_streams: int = 64
    max_per_tenant: int = 16
    max_per_owner: int = 4
    lease_seconds: float = 5
    max_seconds: float = 60

    def __post_init__(self):
        for value in (self.max_streams, self.max_per_tenant, self.max_per_owner):
            if type(value) is not int or not 1 <= value <= 10000:
                raise ValueError("bounded fleet stream capacity required")
        for value, minimum, maximum in ((self.lease_seconds, .05, 30), (self.max_seconds, .05, 3600)):
            if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError("bounded fleet stream timing required")
        if self.lease_seconds > self.max_seconds:
            raise ValueError("lease must fit stream lifetime")


@dataclass(frozen=True)
class StreamLease:
    identity: str
    tenant: str
    owner: str
    scope: str


class DurableStreamLeases:
    """Private coordination metadata in the authority namespace, never task data.

    Policy persists once; a replica with different limits fails startup. Operator
    policy migration is deliberately separate. Directory locks precede the stream
    lock, and no network await holds either. DB time owns lease expiry.
    """
    def __init__(self, directory, *, limits=None):
        self.directory, self.store = directory, directory.store
        self.postgres = isinstance(self.store, PostgresStore)
        self.limits = FleetStreamLimits() if limits is None else limits
        if not isinstance(self.limits, FleetStreamLimits):
            raise ValueError("validated fleet stream limits required")
        self.policy = json.dumps(asdict(self.limits), sort_keys=True, separators=(",", ":"))
        with directory._transaction(write=True, bootstrap=True):
            with self._atomic() as cur:
                tables = ("stream_lease_policy_v1", "stream_leases_v1")
                if self.postgres:
                    present = self._execute(cur, "SELECT c.relname AS name,c.relkind AS kind FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname IN (?,?)", tables).fetchall()
                    if any(row["kind"] != "r" for row in present):
                        raise StreamCapacity("ordinary stream lease tables required")
                else:
                    present = self._execute(cur, "SELECT name,type AS kind FROM sqlite_master WHERE name IN (?,?)", tables).fetchall()
                    if any(row["kind"] != "table" for row in present):
                        raise StreamCapacity("ordinary stream lease tables required")
                if len(present) not in (0, 2):
                    raise StreamCapacity("partial stream lease schema")
                if not present:
                    self._execute(cur, "CREATE TABLE stream_lease_policy_v1(singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL,policy TEXT NOT NULL)")
                    self._execute(cur, "CREATE TABLE stream_leases_v1(identity TEXT PRIMARY KEY,tenant TEXT NOT NULL,owner TEXT NOT NULL,scope TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL,deadline DOUBLE PRECISION NOT NULL)")
                    self._execute(cur, "CREATE INDEX stream_lease_expiry_v1 ON stream_leases_v1(expires)")
                    self._execute(cur, "INSERT INTO stream_lease_policy_v1 VALUES(1,1,?)", (self.policy,))
                self._check(cur)

    def _execute(self, cur, sql, args=()):
        return cur.execute(sql.replace("?", "%s") if self.postgres else sql, args)

    @contextmanager
    def _atomic(self):
        with sql_atomic(self.store):
            cur = self.store._db.cursor()
            try:
                if self.postgres:
                    self._execute(cur, "SELECT pg_advisory_xact_lock(?)", (911007,))
                yield cur
            finally:
                cur.close()

    def _check(self, cur):
        rows = self._execute(cur, "SELECT singleton,version,policy FROM stream_lease_policy_v1").fetchall()
        if len(rows) != 1 or rows[0]["singleton"] != 1 or rows[0]["version"] != 1 or rows[0]["policy"] != self.policy:
            raise StreamCapacity("stream policy missing, changed or unsupported")

    def _now(self, cur):
        sql = "SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS stamp" if self.postgres else "SELECT (julianday('now')-2440587.5)*86400.0 AS stamp"
        return float(self._execute(cur, sql).fetchone()["stamp"])

    @staticmethod
    def _scope(principal):
        # Import locally to avoid kernel/coordinator construction cycles.
        from .tenant_kernel import principal_owner
        return principal_owner(principal)

    def acquire(self, principal):
        with self.directory.guard(principal), self._atomic() as cur:
            owner, scope = quota_owner(principal), self._scope(principal)
            self._check(cur)
            now = self._now(cur)
            # Only ephemeral allocation metadata expires; no history/evidence is deleted.
            self._execute(cur, "DELETE FROM stream_leases_v1 WHERE expires<=? OR deadline<=?", (now, now))
            row = self._execute(cur, "SELECT COUNT(*) AS total,COALESCE(SUM(CASE WHEN tenant=? THEN 1 ELSE 0 END),0) AS tenant_count,COALESCE(SUM(CASE WHEN owner=? THEN 1 ELSE 0 END),0) AS owner_count FROM stream_leases_v1", (principal.tenant_id, owner)).fetchone()
            if row["total"] >= self.limits.max_streams or row["tenant_count"] >= self.limits.max_per_tenant or row["owner_count"] >= self.limits.max_per_owner:
                raise StreamCapacity("shared stream capacity reached")
            lease = StreamLease(secrets.token_hex(32), principal.tenant_id, owner, scope)
            self._execute(cur, "INSERT INTO stream_leases_v1 VALUES(?,?,?,?,?,?)", (lease.identity, lease.tenant, owner, scope, now+self.limits.lease_seconds, now+self.limits.max_seconds))
            return lease

    def renew(self, principal, lease):
        with self.directory.guard(principal), self._atomic() as cur:
            self._check(cur)
            if not isinstance(lease, StreamLease) or lease.tenant != principal.tenant_id or lease.owner != quota_owner(principal) or lease.scope != self._scope(principal):
                raise AuthorityDenied("stream allocation scope unavailable")
            now = self._now(cur)
            row = self._execute(cur, "SELECT deadline FROM stream_leases_v1 WHERE identity=? AND tenant=? AND owner=? AND scope=? AND expires>? AND deadline>?", (lease.identity, lease.tenant, lease.owner, lease.scope, now, now)).fetchone()
            if row is None:
                raise StreamCapacity("stream allocation expired or released")
            self._execute(cur, "UPDATE stream_leases_v1 SET expires=? WHERE identity=?", (min(now+self.limits.lease_seconds, row["deadline"]), lease.identity))

    def release(self, lease):
        if not isinstance(lease, StreamLease):
            raise ValueError("stream allocation required")
        # Cleanup is possible after revocation. The opaque allocation stays server-side.
        with self._atomic() as cur:
            self._execute(cur, "DELETE FROM stream_leases_v1 WHERE identity=? AND tenant=? AND owner=? AND scope=?", (lease.identity, lease.tenant, lease.owner, lease.scope))

    def usage(self):
        with self._atomic() as cur:
            self._check(cur)
            now = self._now(cur)
            row = self._execute(cur, "SELECT COUNT(*) AS active FROM stream_leases_v1 WHERE expires>? AND deadline>?", (now, now)).fetchone()
            return {"active_stream_allocations": row["active"], **asdict(self.limits)}
