"""
Durable persistence for the governance plane.

Two backends behind one interface:
  - InMemoryStore: default; fast, ephemeral (tests/dev).
  - SqliteStore:   durable across restarts (identities, budgets, append-only audit).

SQLite is used because it needs no external service and gives real durability. The
interface (`GovernanceStore`) is the seam to drop in Postgres later for scale — same
method surface, swap the implementation.
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
