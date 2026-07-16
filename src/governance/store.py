"""
Durable persistence for the governance plane.

Three backends behind one interface:
  - InMemoryStore: default; fast, ephemeral (tests/dev).
  - SqliteStore:   durable across restarts, single node (identities, budgets, audit).
  - PostgresStore: durable + multi-instance (shared state for horizontally-scaled
                   control planes). Same method surface; opt in via a postgres URL.

Pick a backend with `make_store(db)`:
  - None / unset      -> InMemoryStore
  - "/path/to.db"     -> SqliteStore
  - "postgres://..."  -> PostgresStore   (requires `psycopg`; pip install psycopg[binary])
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .resilience import retry_transient


class GovernanceStore(ABC):
    # identities
    @abstractmethod
    def upsert_identity(self, agent_id: str, public_key_hex: str, revoked: bool = False) -> None: ...
    @abstractmethod
    def get_identity(self, agent_id: str) -> Optional[Dict[str, Any]]: ...
    @abstractmethod
    def list_identities(self) -> List[Dict[str, Any]]: ...

    # budgets
    @abstractmethod
    def upsert_budget(self, agent_id: str, state: Dict[str, Any]) -> None: ...
    @abstractmethod
    def get_budget(self, agent_id: str) -> Optional[Dict[str, Any]]: ...

    # audit (append-only)
    @abstractmethod
    def append_audit(self, entry: Dict[str, Any]) -> None: ...
    @abstractmethod
    def load_audit(self) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def truncate_audit_before(self, seq: int) -> int:
        """Delete audit entries with seq < `seq`. Returns the number deleted.
        Implementations MUST be a no-op (return 0) when seq <= 0."""

    # approvals (store-backed; new in production-readiness pass)
    @abstractmethod
    def insert_approval(self, approval: Dict[str, Any]) -> None: ...
    @abstractmethod
    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]: ...
    @abstractmethod
    def list_approvals(self, status: Optional[str] = None) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def update_approval_status(self, approval_id: str, status: str) -> bool: ...
    @abstractmethod
    def consume_approval(self, approval_id: str) -> bool:
        """Atomically transition an approval from 'approved' to 'consumed'.
        Returns True on success, False if the row doesn't exist or isn't 'approved'.
        Distinct from update_approval_status (which only allows pending->approved/denied)."""
    @abstractmethod
    def delete_approval(self, approval_id: str) -> bool: ...

    # --- atomic, cross-process-safe operations (fix multi-worker fork/double-spend) ---
    @abstractmethod
    def append_audit_chained(self, build_entry) -> Dict[str, Any]:
        """Atomically determine the next (seq, prev_hash) from the DURABLE head, call
        build_entry(seq, prev_hash) -> entry dict, persist it, and return it. Serialized
        across processes so the hash chain cannot fork under multiple workers."""

    @abstractmethod
    def mutate_budget(self, agent_id: str, mutator) -> Any:
        """Atomically read a budget's persisted state, call mutator(state) (which may mutate
        state in place and return a result), persist the new state, and return the result.
        Serialized across processes so concurrent reserve/commit cannot double-spend."""


class InMemoryStore(GovernanceStore):
    GENESIS = "0" * 64

    def __init__(self):
        self._identities: Dict[str, Dict[str, Any]] = {}
        self._budgets: Dict[str, Dict[str, Any]] = {}
        self._audit: List[Dict[str, Any]] = []
        self._approvals: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def upsert_identity(self, agent_id, public_key_hex, revoked=False):
        self._identities[agent_id] = {"agent_id": agent_id,
                                      "public_key_hex": public_key_hex,
                                      "revoked": revoked}

    def get_identity(self, agent_id):
        return self._identities.get(agent_id)

    def list_identities(self):
        return list(self._identities.values())

    def upsert_budget(self, agent_id, state):
        self._budgets[agent_id] = {"agent_id": agent_id, **state}

    def get_budget(self, agent_id):
        return self._budgets.get(agent_id)

    def append_audit(self, entry):
        with self._lock:
            self._audit.append(dict(entry))

    def load_audit(self):
        with self._lock:
            return [dict(e) for e in self._audit]

    def truncate_audit_before(self, seq):
        if seq <= 0:
            return 0
        with self._lock:
            before = len(self._audit)
            self._audit = [e for e in self._audit if e["seq"] >= seq]
            return before - len(self._audit)

    def append_audit_chained(self, build_entry):
        with self._lock:
            last = self._audit[-1] if self._audit else None
            seq = (last["seq"] + 1) if last else 0
            prev_hash = last["entry_hash"] if last else self.GENESIS
            entry = build_entry(seq, prev_hash)
            self._audit.append(dict(entry))
            return entry

    def mutate_budget(self, agent_id, mutator):
        with self._lock:
            rec = self._budgets.get(agent_id)
            state = {k: v for k, v in rec.items() if k != "agent_id"} if rec else {}
            result = mutator(state)
            self._budgets[agent_id] = {"agent_id": agent_id, **state}
            return result

    # --- approvals ---
    def insert_approval(self, approval):
        with self._lock:
            self._approvals[approval["id"]] = dict(approval)

    def get_approval(self, approval_id):
        with self._lock:
            rec = self._approvals.get(approval_id)
            return dict(rec) if rec else None

    def list_approvals(self, status=None):
        with self._lock:
            return [dict(a) for a in self._approvals.values()
                    if status is None or a.get("status") == status]

    def update_approval_status(self, approval_id, status):
        with self._lock:
            rec = self._approvals.get(approval_id)
            if rec is None or rec["status"] != "pending":
                return False
            rec["status"] = status
            return True

    def consume_approval(self, approval_id):
        with self._lock:
            rec = self._approvals.get(approval_id)
            if rec is None or rec["status"] != "approved":
                return False
            rec["status"] = "consumed"
            return True

    def delete_approval(self, approval_id):
        with self._lock:
            return self._approvals.pop(approval_id, None) is not None


class SqliteStore(GovernanceStore):
    """Durable store, safe across processes. isolation_level=None lets us run explicit
    BEGIN IMMEDIATE transactions so the chained-append and budget-mutate are serialized
    across multiple workers (SQLite file lock); busy_timeout makes contenders wait."""

    GENESIS = "0" * 64

    def __init__(self, path: str = "agentbridge_governance.db"):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS identities (
                    agent_id TEXT PRIMARY KEY,
                    public_key_hex TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS budgets (
                    agent_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY,
                    entry TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    cost REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
                CREATE INDEX IF NOT EXISTS idx_approvals_agent ON approvals(agent_id);
                """
            )
            self._db.commit()

    def upsert_identity(self, agent_id, public_key_hex, revoked=False):
        with self._lock:
            self._db.execute(
                "INSERT INTO identities(agent_id, public_key_hex, revoked) VALUES(?,?,?) "
                "ON CONFLICT(agent_id) DO UPDATE SET public_key_hex=excluded.public_key_hex, "
                "revoked=excluded.revoked",
                (agent_id, public_key_hex, 1 if revoked else 0),
            )
            self._db.commit()

    def get_identity(self, agent_id):
        with self._lock:
            row = self._db.execute(
                "SELECT agent_id, public_key_hex, revoked FROM identities WHERE agent_id=?",
                (agent_id,)).fetchone()
        if not row:
            return None
        return {"agent_id": row["agent_id"], "public_key_hex": row["public_key_hex"],
                "revoked": bool(row["revoked"])}

    def list_identities(self):
        with self._lock:
            rows = self._db.execute(
                "SELECT agent_id, public_key_hex, revoked FROM identities").fetchall()
        return [{"agent_id": r["agent_id"], "public_key_hex": r["public_key_hex"],
                 "revoked": bool(r["revoked"])} for r in rows]

    def upsert_budget(self, agent_id, state):
        with self._lock:
            self._db.execute(
                "INSERT INTO budgets(agent_id, state) VALUES(?,?) "
                "ON CONFLICT(agent_id) DO UPDATE SET state=excluded.state",
                (agent_id, json.dumps(state)))
            self._db.commit()

    def get_budget(self, agent_id):
        with self._lock:
            row = self._db.execute("SELECT state FROM budgets WHERE agent_id=?",
                                   (agent_id,)).fetchone()
        return json.loads(row["state"]) if row else None

    def append_audit(self, entry):
        with self._lock:
            self._db.execute("INSERT INTO audit(seq, entry) VALUES(?,?)",
                             (entry["seq"], json.dumps(entry)))
            self._db.commit()

    def load_audit(self):
        with self._lock:
            rows = self._db.execute("SELECT entry FROM audit ORDER BY seq").fetchall()
        return [json.loads(r["entry"]) for r in rows]

    def truncate_audit_before(self, seq):
        if seq <= 0:
            return 0
        with self._lock:
            cur = self._db.execute("DELETE FROM audit WHERE seq < ?", (seq,))
            self._db.commit()
            return cur.rowcount or 0

    def append_audit_chained(self, build_entry):
        @retry_transient(max_attempts=4, base_delay=0.01, max_delay=0.5)
        def _go():
            with self._lock:
                self._db.execute("BEGIN IMMEDIATE")          # write lock -> serialize across procs
                try:
                    row = self._db.execute(
                        "SELECT seq, entry FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
                    if row:
                        last = json.loads(row["entry"])
                        seq, prev_hash = last["seq"] + 1, last["entry_hash"]
                    else:
                        seq, prev_hash = 0, self.GENESIS
                    entry = build_entry(seq, prev_hash)
                    self._db.execute("INSERT INTO audit(seq, entry) VALUES(?,?)",
                                     (entry["seq"], json.dumps(entry)))
                    self._db.execute("COMMIT")
                    return entry
                except Exception:
                    self._db.execute("ROLLBACK")
                    raise
        return _go()

    def mutate_budget(self, agent_id, mutator):
        @retry_transient(max_attempts=4, base_delay=0.01, max_delay=0.5)
        def _go():
            with self._lock:
                self._db.execute("BEGIN IMMEDIATE")
                try:
                    row = self._db.execute("SELECT state FROM budgets WHERE agent_id=?",
                                           (agent_id,)).fetchone()
                    state = json.loads(row["state"]) if row else {}
                    result = mutator(state)
                    self._db.execute(
                        "INSERT INTO budgets(agent_id, state) VALUES(?,?) "
                        "ON CONFLICT(agent_id) DO UPDATE SET state=excluded.state",
                        (agent_id, json.dumps(state)))
                    self._db.execute("COMMIT")
                    return result
                except Exception:
                    self._db.execute("ROLLBACK")
                    raise
        return _go()

    # --- approvals (atomic status update so multi-worker approve/deny is race-free) ---
    def insert_approval(self, approval):
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO approvals(id, agent_id, capability, cost, status, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (approval["id"], approval["agent_id"], approval["capability"],
                 float(approval["cost"]), approval.get("status", "pending"),
                 approval.get("created_at", "")),
            )
            self._db.commit()

    def get_approval(self, approval_id):
        with self._lock:
            row = self._db.execute(
                "SELECT id, agent_id, capability, cost, status, created_at "
                "FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "agent_id": row["agent_id"],
                "capability": row["capability"], "cost": row["cost"],
                "status": row["status"], "created_at": row["created_at"]}

    def list_approvals(self, status=None):
        with self._lock:
            if status is None:
                rows = self._db.execute(
                    "SELECT id, agent_id, capability, cost, status, created_at "
                    "FROM approvals ORDER BY created_at").fetchall()
            else:
                rows = self._db.execute(
                    "SELECT id, agent_id, capability, cost, status, created_at "
                    "FROM approvals WHERE status=? ORDER BY created_at", (status,)).fetchall()
        return [{"id": r["id"], "agent_id": r["agent_id"], "capability": r["capability"],
                 "cost": r["cost"], "status": r["status"], "created_at": r["created_at"]}
                for r in rows]

    def update_approval_status(self, approval_id, status):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
                if not row or row["status"] != "pending":
                    self._db.execute("ROLLBACK")
                    return False
                self._db.execute("UPDATE approvals SET status=? WHERE id=?",
                                 (status, approval_id))
                self._db.execute("COMMIT")
                return True
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def consume_approval(self, approval_id):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
                if not row or row["status"] != "approved":
                    self._db.execute("ROLLBACK")
                    return False
                self._db.execute("UPDATE approvals SET status='consumed' WHERE id=?",
                                 (approval_id,))
                self._db.execute("COMMIT")
                return True
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def delete_approval(self, approval_id):
        with self._lock:
            cur = self._db.execute("DELETE FROM approvals WHERE id=?", (approval_id,))
            self._db.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._db.close()


class PostgresStore(GovernanceStore):
    """Durable, multi-instance store backed by Postgres.

    Mirrors SqliteStore exactly behind the same interface, so the governance plane
    (identities/budgets/audit) gets shared state across horizontally-scaled control
    planes. `psycopg` (v3) is imported lazily, so it's only required when you actually
    choose a postgres URL — the default SQLite/in-memory paths need no extra deps.

    Verified against real postgres:16 — identity/budget/audit roundtrips AND the multi-worker
    advisory-lock concurrency path (audit chain doesn't fork, budgets don't double-spend across
    separate connections). Integration tests: tests/test_postgres_store.py (6 tests, skipped
    unless AGENTBRIDGE_TEST_PG points at a throwaway database). Still validate against your own
    managed Postgres before production reliance.
    """

    GENESIS = "0" * 64

    def __init__(self, dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as e:  # pragma: no cover - exercised only without the dep
            raise RuntimeError(
                "PostgresStore needs the 'psycopg' package. Install it with "
                "`pip install \"psycopg[binary]\"`, or use a SQLite path instead."
            ) from e
        self._lock = threading.RLock()
        self._db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._init_schema()

    def _init_schema(self):
        with self._lock, self._db.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS identities (
                    agent_id TEXT PRIMARY KEY,
                    public_key_hex TEXT NOT NULL,
                    revoked BOOLEAN NOT NULL DEFAULT FALSE
                );
                CREATE TABLE IF NOT EXISTS budgets (
                    agent_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq BIGINT PRIMARY KEY,
                    entry TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    cost DOUBLE PRECISION NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
                CREATE INDEX IF NOT EXISTS idx_approvals_agent ON approvals(agent_id);
                """
            )

    def upsert_identity(self, agent_id, public_key_hex, revoked=False):
        with self._lock, self._db.cursor() as cur:
            cur.execute(
                "INSERT INTO identities(agent_id, public_key_hex, revoked) VALUES(%s,%s,%s) "
                "ON CONFLICT(agent_id) DO UPDATE SET public_key_hex=EXCLUDED.public_key_hex, "
                "revoked=EXCLUDED.revoked",
                (agent_id, public_key_hex, bool(revoked)),
            )

    def get_identity(self, agent_id):
        with self._lock, self._db.cursor() as cur:
            cur.execute(
                "SELECT agent_id, public_key_hex, revoked FROM identities WHERE agent_id=%s",
                (agent_id,))
            row = cur.fetchone()
        if not row:
            return None
        return {"agent_id": row["agent_id"], "public_key_hex": row["public_key_hex"],
                "revoked": bool(row["revoked"])}

    def list_identities(self):
        with self._lock, self._db.cursor() as cur:
            cur.execute("SELECT agent_id, public_key_hex, revoked FROM identities")
            rows = cur.fetchall()
        return [{"agent_id": r["agent_id"], "public_key_hex": r["public_key_hex"],
                 "revoked": bool(r["revoked"])} for r in rows]

    def upsert_budget(self, agent_id, state):
        with self._lock, self._db.cursor() as cur:
            cur.execute(
                "INSERT INTO budgets(agent_id, state) VALUES(%s,%s) "
                "ON CONFLICT(agent_id) DO UPDATE SET state=EXCLUDED.state",
                (agent_id, json.dumps(state)))

    def get_budget(self, agent_id):
        with self._lock, self._db.cursor() as cur:
            cur.execute("SELECT state FROM budgets WHERE agent_id=%s", (agent_id,))
            row = cur.fetchone()
        return json.loads(row["state"]) if row else None

    def append_audit(self, entry):
        with self._lock, self._db.cursor() as cur:
            cur.execute("INSERT INTO audit(seq, entry) VALUES(%s,%s) "
                        "ON CONFLICT(seq) DO NOTHING",
                        (entry["seq"], json.dumps(entry)))

    def load_audit(self):
        with self._lock, self._db.cursor() as cur:
            cur.execute("SELECT entry FROM audit ORDER BY seq")
            rows = cur.fetchall()
        return [json.loads(r["entry"]) for r in rows]

    def truncate_audit_before(self, seq):
        if seq <= 0:
            return 0
        with self._lock, self._db.cursor() as cur:
            cur.execute("DELETE FROM audit WHERE seq < %s", (seq,))
            return cur.rowcount or 0

    # Cluster-wide serialization via transaction-scoped advisory locks (distinct keys so
    # audit appends and budget mutations don't block each other unnecessarily).
    _AUDIT_LOCK_KEY = 911001

    def append_audit_chained(self, build_entry):
        @retry_transient(max_attempts=4, base_delay=0.01, max_delay=0.5)
        def _go():
            with self._lock, self._db.transaction(), self._db.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._AUDIT_LOCK_KEY,))
                cur.execute("SELECT seq, entry FROM audit ORDER BY seq DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    last = json.loads(row["entry"])
                    seq, prev_hash = last["seq"] + 1, last["entry_hash"]
                else:
                    seq, prev_hash = 0, self.GENESIS
                entry = build_entry(seq, prev_hash)
                cur.execute("INSERT INTO audit(seq, entry) VALUES(%s,%s)",
                            (entry["seq"], json.dumps(entry)))
                return entry
        return _go()

    def mutate_budget(self, agent_id, mutator):
        @retry_transient(max_attempts=4, base_delay=0.01, max_delay=0.5)
        def _go():
            with self._lock, self._db.transaction(), self._db.cursor() as cur:
                # per-agent advisory lock so different agents don't serialize against each other
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"budget:{agent_id}",))
                cur.execute("SELECT state FROM budgets WHERE agent_id=%s", (agent_id,))
                row = cur.fetchone()
                state = json.loads(row["state"]) if row else {}
                result = mutator(state)
                cur.execute("INSERT INTO budgets(agent_id, state) VALUES(%s,%s) "
                            "ON CONFLICT(agent_id) DO UPDATE SET state=EXCLUDED.state",
                            (agent_id, json.dumps(state)))
                return result
        return _go()

    # --- approvals (atomic via transaction + row-level lock) ---
    _APPROVAL_LOCK_KEY = 911002

    def insert_approval(self, approval):
        with self._lock, self._db.cursor() as cur:
            cur.execute(
                "INSERT INTO approvals(id, agent_id, capability, cost, status, created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (approval["id"], approval["agent_id"], approval["capability"],
                 float(approval["cost"]), approval.get("status", "pending"),
                 approval.get("created_at", "")),
            )

    def get_approval(self, approval_id):
        with self._lock, self._db.cursor() as cur:
            cur.execute(
                "SELECT id, agent_id, capability, cost, status, created_at "
                "FROM approvals WHERE id=%s", (approval_id,))
            row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def list_approvals(self, status=None):
        with self._lock, self._db.cursor() as cur:
            if status is None:
                cur.execute("SELECT id, agent_id, capability, cost, status, created_at "
                            "FROM approvals ORDER BY created_at")
            else:
                cur.execute("SELECT id, agent_id, capability, cost, status, created_at "
                            "FROM approvals WHERE status=%s ORDER BY created_at", (status,))
            return [dict(r) for r in cur.fetchall()]

    def update_approval_status(self, approval_id, status):
        with self._lock, self._db.transaction(), self._db.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._APPROVAL_LOCK_KEY,))
            cur.execute("SELECT status FROM approvals WHERE id=%s FOR UPDATE", (approval_id,))
            row = cur.fetchone()
            if not row or row["status"] != "pending":
                return False
            cur.execute("UPDATE approvals SET status=%s WHERE id=%s",
                        (status, approval_id))
            return True

    def consume_approval(self, approval_id):
        with self._lock, self._db.transaction(), self._db.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._APPROVAL_LOCK_KEY,))
            cur.execute("SELECT status FROM approvals WHERE id=%s FOR UPDATE", (approval_id,))
            row = cur.fetchone()
            if not row or row["status"] != "approved":
                return False
            cur.execute("UPDATE approvals SET status='consumed' WHERE id=%s",
                        (approval_id,))
            return True

    def delete_approval(self, approval_id):
        with self._lock, self._db.cursor() as cur:
            cur.execute("DELETE FROM approvals WHERE id=%s", (approval_id,))
            return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._db.close()


def make_store(db: Optional[str]) -> GovernanceStore:
    """Choose a backend from a connection string.

    None/empty -> InMemoryStore; a postgres URL -> PostgresStore; anything else
    treated as a SQLite file path.
    """
    if not db:
        return InMemoryStore()
    if db.startswith("postgres://") or db.startswith("postgresql://"):
        return PostgresStore(db)
    return SqliteStore(db)
