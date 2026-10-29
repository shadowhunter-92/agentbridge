"""PostgreSQL-side monotonic leader lease and fencing epoch.

The epoch must be checked by EVERY consequential target before accepting a
write. An SQL fence alone does not prevent a partitioned old primary from
acting in another system. Do not call this split-brain-safe without a single
authoritative fencing service/target.
"""
import math
import psycopg
from psycopg.conninfo import conninfo_to_dict


class FenceDenied(RuntimeError):
    pass


def _bounded_connection(dsn, **kwargs):
    """Bound setup and server-side SQL waits; never retry an uncertain action."""
    options = conninfo_to_dict(dsn).get("options", "")
    options += " -cstatement_timeout=10000 -clock_timeout=5000"
    return psycopg.connect(dsn, connect_timeout=5, options=options, **kwargs)


class PgFencing:
    def __init__(self, dsn):
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("PostgreSQL fencing DSN required")
        self.dsn = dsn

    @staticmethod
    def _validate(scope, owner):
        if not all(isinstance(v,str) and 1<=len(v)<=128 for v in (scope,owner)):
            raise FenceDenied("scope and owner must be nonempty bounded identities")

    def initialize(self):
        with _bounded_connection(self.dsn,autocommit=True) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS agentbridge_fences ("
                "scope TEXT PRIMARY KEY, owner TEXT NOT NULL, epoch BIGINT NOT NULL "
                "CHECK(epoch>=1), expires TIMESTAMPTZ NOT NULL)")

    def acquire(self, scope, owner, *, ttl_seconds=30):
        self._validate(scope,owner)
        if (not isinstance(ttl_seconds,(int,float)) or isinstance(ttl_seconds,bool)
                or not math.isfinite(ttl_seconds) or not 0.5<=ttl_seconds<=3600):
            raise FenceDenied("invalid bounded lease duration")
        with _bounded_connection(self.dsn,autocommit=True) as c:
            row=c.execute(
                "INSERT INTO agentbridge_fences AS f(scope,owner,epoch,expires) "
                "VALUES(%s,%s,1,clock_timestamp()+%s * interval '1 second') "
                "ON CONFLICT(scope) DO UPDATE SET "
                "owner=EXCLUDED.owner,epoch=f.epoch+1,"
                "expires=clock_timestamp()+%s * interval '1 second' "
                "WHERE f.expires<=clock_timestamp() "
                "RETURNING epoch",(scope,owner,ttl_seconds,ttl_seconds)).fetchone()
        if row is None:
            raise FenceDenied("leadership already held")
        return int(row[0])

    def renew(self,scope,owner,epoch,*,ttl_seconds=30):
        self._validate(scope,owner)
        if (not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<1
                or not isinstance(ttl_seconds,(int,float)) or isinstance(ttl_seconds,bool)
                or not math.isfinite(ttl_seconds) or not 0.5<=ttl_seconds<=3600):
            raise FenceDenied("invalid fence token or lease duration")
        with _bounded_connection(self.dsn,autocommit=True) as c:
            with c.transaction():
                # A volatile WHERE expression can precede a lock wait.
                # Own the row before a later statement reads the live clock.
                locked=c.execute(
                    "SELECT 1 FROM agentbridge_fences WHERE scope=%s FOR UPDATE",
                    (scope,)).fetchone()
                if locked is None:
                    raise FenceDenied("stale or expired fencing epoch")
                row=c.execute(
                    "UPDATE agentbridge_fences SET "
                    "expires=clock_timestamp()+%s * interval '1 second' "
                    "WHERE scope=%s AND owner=%s AND epoch=%s "
                    "AND expires>clock_timestamp() RETURNING epoch",
                    (ttl_seconds,scope,owner,epoch)).fetchone()
        if row is None:
            raise FenceDenied("stale or expired fencing epoch")
        return int(row[0])

    def check(self,scope,owner,epoch):
        self._validate(scope,owner)
        if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<1:
            return False
        with _bounded_connection(self.dsn,autocommit=True) as c:
            row=c.execute(
                "SELECT 1 FROM agentbridge_fences WHERE "
                "scope=%s AND owner=%s AND epoch=%s AND expires>clock_timestamp()",
                (scope,owner,epoch)).fetchone()
        return row is not None
