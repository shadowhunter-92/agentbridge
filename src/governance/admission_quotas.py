"""Durable aggregate admission caps; operation state remains the outcome authority.

Policy is operator-enabled. Unknown operations never expire out of exposure.
Historical unattributed usage is conservatively charged to every quota owner.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .authority import AuthorityDenied, _identifier, _subject
from .budget import _checked_cost
from .store import PostgresStore, SqliteStore, sql_atomic
from .tenant_store import _quote


class QuotaDenied(ValueError):
    pass


@dataclass(frozen=True)
class QuotaLimits:
    enabled: bool = False
    spend_limit: float = 1000.0
    user_spend_limit: float = 100.0
    rate_limit: int = 10000
    user_rate_limit: int = 1000
    window_seconds: int = 3600
    max_active: int = 128
    user_max_active: int = 32
    max_records: int = 100000

    def validated(self):
        if type(self.enabled) is not bool:
            raise ValueError("explicit quota activation boolean required")
        for field in ("spend_limit", "user_spend_limit"):
            if type(getattr(self, field)) not in (int, float):
                raise ValueError("finite numeric quota " + field + " required")
            _checked_cost(getattr(self, field))
        for field, maximum in (
            ("rate_limit", 1000000),
            ("user_rate_limit", 1000000),
            ("window_seconds", 31536000),
            ("max_active", 1000000),
            ("user_max_active", 1000000),
            ("max_records", 10000000),
        ):
            if type(getattr(self, field)) is not int or not 1 <= getattr(self, field) <= maximum:
                raise ValueError("invalid bounded quota " + field)
        return self


def quota_owner(principal):
    """Stable enrolled human/machine owner, distinct from exact-scope view ownership."""
    if principal.kind not in ("machine", "delegated_human"):
        raise AuthorityDenied("agent quota owner required")
    issuer = principal.issuer
    if not isinstance(issuer, str) or not 1 <= len(issuer) <= 2048 or any(ord(c) < 32 for c in issuer):
        raise AuthorityDenied("invalid quota issuer")
    material = {
        "domain": "agentbridge.quota-owner.v1",
        "tenant_id": _identifier(principal.tenant_id, "tenant_id"),
        "kind": principal.kind,
        "issuer": issuer,
        "subject": _subject(principal.subject),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AdmissionQuotas:
    """One policy/fence per private tenant SQL namespace, shared by replicas.

    These records preserve attribution/cost, not a second outcome implementation.
    Limits can be lowered without cancelling or discarding existing exposure.
    Saturated history fails closed; this component never deletes evidence/history.
    """

    def __init__(self, store):
        if not isinstance(store, (SqliteStore, PostgresStore)) or not getattr(store, "tenant_id", None):
            raise ValueError("private bound tenant SQL store required")
        self.store = store
        self.postgres = isinstance(store, PostgresStore)
        with sql_atomic(store):
            if self.postgres:
                self._execute("SELECT pg_advisory_xact_lock(?)", (911004,))
            self._execute(
                "CREATE TABLE IF NOT EXISTS admission_quota_policy_v1 ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL,policy TEXT NOT NULL)"
            )
            self._execute(
                "CREATE TABLE IF NOT EXISTS admission_quota_records_v1 ("
                "agent_id TEXT NOT NULL,operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,"
                "owner TEXT NOT NULL,cost DOUBLE PRECISION NOT NULL,admitted DOUBLE PRECISION NOT NULL,"
                "PRIMARY KEY(agent_id,operation_id))"
            )
            self._execute(
                "CREATE INDEX IF NOT EXISTS admission_quota_owner_time_v1 ON admission_quota_records_v1(owner,admitted)"
            )
            self._execute(
                "INSERT INTO admission_quota_policy_v1 VALUES(1,1,?) ON CONFLICT(singleton) DO NOTHING",
                (json.dumps(asdict(QuotaLimits()), sort_keys=True),),
            )
            self._policy()
            self._install_claim_guard()
        store.seal_writes()

    def _execute(self, query, values=()):
        return self.store._db.execute(query.replace("?", "%s") if self.postgres else query, values)

    def _lock(self):
        if self.postgres:
            self._execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(?,0))", ("agentbridge.quota.v1:" + self.store.store_id,)
            )

    def _now(self):
        query = (
            "SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now"
            if self.postgres
            else "SELECT (julianday('now')-2440587.5)*86400.0 AS now"
        )
        return float(self._execute(query).fetchone()["now"])

    def _policy(self):
        row = self._execute("SELECT version,policy FROM admission_quota_policy_v1 WHERE singleton=1").fetchone()
        try:
            if row is None or row["version"] != 1:
                raise ValueError("unsupported quota version")
            data = json.loads(row["policy"])
            if not isinstance(data, dict) or set(data) != set(asdict(QuotaLimits())):
                raise ValueError("complete explicit quota policy required")
            return QuotaLimits(**data).validated()
        except (TypeError, ValueError) as exc:
            raise QuotaDenied("missing, altered or unsupported quota policy") from exc

    def _install_claim_guard(self):
        # Older tenant workers cannot insert an operation under enabled caps
        # without the matching atomic quota admission record. No session flag
        # or cached Python optional setting grants an exception.
        if not self.postgres:
            self._execute("DROP TRIGGER IF EXISTS admission_quota_claim_guard_v1")
            self._execute(
                "CREATE TRIGGER admission_quota_claim_guard_v1 "
                "BEFORE INSERT ON agent_operations WHEN "
                "(COALESCE((SELECT version FROM admission_quota_policy_v1 WHERE singleton=1),0)<>1 OR "
                "COALESCE(json_extract((SELECT policy FROM admission_quota_policy_v1 WHERE singleton=1),'$.enabled'),1)<>0) "
                "AND NOT EXISTS (SELECT 1 FROM admission_quota_records_v1 "
                "WHERE agent_id=NEW.agent_id AND operation_id=NEW.operation_id AND fingerprint=NEW.fingerprint) "
                "BEGIN SELECT RAISE(ABORT,'atomic quota admission required'); END"
            )
        else:
            schema = _quote(self.store.schema)
            function = schema + ".admission_quota_claim_guard_v1"
            self._execute(
                "CREATE OR REPLACE FUNCTION " + function + "() RETURNS trigger LANGUAGE plpgsql "
                "SET search_path=pg_catalog AS $$ BEGIN IF "
                "(COALESCE((SELECT version FROM " + schema + ".admission_quota_policy_v1 WHERE singleton=1),0)<>1 OR "
                "COALESCE((SELECT (policy::jsonb->>'enabled')::boolean FROM "
                + schema
                + ".admission_quota_policy_v1 WHERE singleton=1),true)) "
                "AND NOT EXISTS (SELECT 1 FROM " + schema + ".admission_quota_records_v1 "
                "WHERE agent_id=NEW.agent_id AND operation_id=NEW.operation_id AND fingerprint=NEW.fingerprint) "
                "THEN RAISE EXCEPTION 'atomic quota admission required'; END IF; RETURN NEW; END $$"
            )
            self._execute("DROP TRIGGER IF EXISTS admission_quota_claim_guard_v1 ON agent_operations")
            self._execute(
                "CREATE TRIGGER admission_quota_claim_guard_v1 BEFORE INSERT ON agent_operations "
                "FOR EACH ROW EXECUTE FUNCTION " + function + "()"
            )

    def set_policy(self, limits, *, audit):
        if not isinstance(limits, QuotaLimits):
            raise ValueError("validated quota limits required")
        limits.validated()
        with sql_atomic(self.store):
            self._lock()
            self._policy()
            self._execute(
                "UPDATE admission_quota_policy_v1 SET policy=? WHERE singleton=1",
                (json.dumps(asdict(limits), sort_keys=True, allow_nan=False),),
            )
            audit()

    def _usage(self, owner, now, limits):
        total = 0.0
        # Current per-agent SQL state includes pre-quota and still-unattributed
        # budgets. Current operation outcomes are read after budget totals;
        # settlement can only preserve or reduce aggregate exposure.
        for row in self._execute("SELECT state FROM budgets").fetchall():
            state = json.loads(row["state"])
            total += _checked_cost(state.get("spent", 0))
            total += sum(_checked_cost(cost) for cost in state.get("reserved", {}).values())
        row = self._execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN o.state IN ('unknown','succeeded') THEN q.cost ELSE 0 END),0) AS attributed,"
            "COALESCE(SUM(CASE WHEN q.owner=? AND o.state IN ('unknown','succeeded') THEN q.cost ELSE 0 END),0) AS owned,"
            "COALESCE(SUM(CASE WHEN o.state='unknown' THEN 1 ELSE 0 END),0) AS active,"
            "COALESCE(SUM(CASE WHEN q.owner=? AND o.state='unknown' THEN 1 ELSE 0 END),0) AS owned_active,"
            "COUNT(*) AS records,"
            "COALESCE(SUM(CASE WHEN q.admitted>? THEN 1 ELSE 0 END),0) AS recent,"
            "COALESCE(SUM(CASE WHEN q.owner=? AND q.admitted>? THEN 1 ELSE 0 END),0) AS owned_recent "
            "FROM admission_quota_records_v1 q JOIN agent_operations o "
            "ON o.agent_id=q.agent_id AND o.operation_id=q.operation_id",
            (owner, owner, now - limits.window_seconds, owner, now - limits.window_seconds),
        ).fetchone()
        legacy = self._execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN o.state='unknown' THEN 1 ELSE 0 END),0) AS active,"
            "COALESCE(SUM(CASE WHEN o.state='unknown' OR o.updated>? THEN 1 ELSE 0 END),0) AS recent "
            "FROM agent_operations o LEFT JOIN admission_quota_records_v1 q "
            "ON o.agent_id=q.agent_id AND o.operation_id=q.operation_id WHERE q.operation_id IS NULL",
            (now - limits.window_seconds,),
        ).fetchone()
        unattributed = max(0.0, total - float(row["attributed"]))
        return {
            "spend": total,
            "user_spend": float(row["owned"]) + unattributed,
            "unattributed_spend": unattributed,
            "active": row["active"] + legacy["active"],
            "user_active": row["owned_active"] + legacy["active"],
            "recent": row["recent"] + legacy["recent"],
            "user_recent": row["owned_recent"] + legacy["recent"],
            "records": row["records"],
        }

    def admit(self, principal, agent_id, operation_id, fingerprint, cost):
        with self.store._lock:
            if self.postgres:
                from psycopg.pq import TransactionStatus

                active = self.store._db.info.transaction_status == TransactionStatus.INTRANS
            else:
                active = self.store._db.in_transaction
            if not active:
                raise RuntimeError("quota admission requires its operation claim transaction")
            return self._admit(principal, agent_id, operation_id, fingerprint, cost)

    def _admit(self, principal, agent_id, operation_id, fingerprint, cost):
        """Called by claim after its operation lock, before operation insertion.

        The surrounding shared admission transaction must reserve/link budget and
        consume approval before commit. This is an internal kernel callback.
        """
        if principal.tenant_id != self.store.tenant_id or principal.agent_id != agent_id:
            raise AuthorityDenied("quota principal does not own admission")
        cost = _checked_cost(cost)
        owner = quota_owner(principal)
        self._lock()
        limits, now = self._policy(), self._now()
        records = self._execute("SELECT COUNT(*) AS n FROM admission_quota_records_v1").fetchone()["n"]
        if records >= limits.max_records:
            raise QuotaDenied("quota history capacity reached; reviewed archival required")
        if limits.enabled:
            usage = self._usage(owner, now, limits)
            checks = (
                (usage["spend"] + cost, limits.spend_limit, "tenant spend"),
                (usage["user_spend"] + cost, limits.user_spend_limit, "user spend"),
                (usage["recent"] + 1, limits.rate_limit, "tenant rate"),
                (usage["user_recent"] + 1, limits.user_rate_limit, "user rate"),
                (usage["active"] + 1, limits.max_active, "tenant active operations"),
                (usage["user_active"] + 1, limits.user_max_active, "user active operations"),
            )
            for exposure, limit, label in checks:
                if exposure > limit:
                    raise QuotaDenied(label + " quota exceeded")
        self._execute(
            "INSERT INTO admission_quota_records_v1 VALUES(?,?,?,?,?,?)",
            (agent_id, operation_id, fingerprint, owner, cost, now),
        )

    def inspect(self):
        with sql_atomic(self.store):
            self._lock()
            limits = self._policy()
            usage = self._usage("", self._now(), limits)
            return {
                "limits": asdict(limits),
                "usage": {key: value for key, value in usage.items() if not key.startswith("user_")},
            }
