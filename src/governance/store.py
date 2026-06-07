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


class InMemoryStore(GovernanceStore):
    def __init__(self):
        self._identities: Dict[str, Dict[str, Any]] = {}
        self._budgets: Dict[str, Dict[str, Any]] = {}
        self._audit: List[Dict[str, Any]] = []

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
        self._audit.append(dict(entry))

    def load_audit(self):
        return [dict(e) for e in self._audit]


class SqliteStore(GovernanceStore):
    """Durable store. Thread-safe via a lock + check_same_thread=False."""

    def __init__(self, path: str = "agentbridge_governance.db"):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
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

    def close(self) -> None:
        with self._lock:
            self._db.close()


class PostgresStore(GovernanceStore):
    """Durable, multi-instance store backed by Postgres.

    Mirrors SqliteStore exactly behind the same interface, so the governance plane
    (identities/budgets/audit) gets shared state across horizontally-scaled control
    planes. `psycopg` (v3) is imported lazily, so it's only required when you actually
    choose a postgres URL — the default SQLite/in-memory paths need no extra deps.

    NOTE: validate against a live Postgres before relying on it in production
    (integration test: tests/test_postgres_store.py, skipped unless AGENTBRIDGE_TEST_PG
    points at a throwaway database).
    """

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
