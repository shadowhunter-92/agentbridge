"""Durable, bounded task-status SDK; never executes or retries an action.

Owners must be authenticated by the embedding service, not taken from task wire
metadata. Cancellation records a lifecycle state, not rollback of an external
effect. The pull-based event iterator supports local cursor recovery, not A2A
wire streaming conformance or independently witnessed event integrity.
"""

from __future__ import annotations

import asyncio
import json
import math
from contextlib import contextmanager
from dataclasses import asdict

from src.governance.store import PostgresStore, SqliteStore, sql_atomic

from .task_lifecycle import LifecycleRejected, TaskLifecycle, TaskState, _identifier


class LifecycleCapacity(LifecycleRejected):
    """The configured active-task or event capacity has been reached."""


class DurableTaskLifecycle:
    """Atomic owner-scoped snapshots and append-only status replay.

    SQLite serializes with BEGIN IMMEDIATE; PostgreSQL uses a transaction advisory
    lock across connections. Limits must be identical across service replicas.
    Local status changes can join sql_atomic on the same store. Initialize the
    service before admitting work; schema setup is not a request-path operation.
    This is application-level persistence, not tamper-proof database storage.
    """

    def __init__(self, store, *, max_active_per_owner=128, max_events_per_task=1024):
        if not isinstance(store, (SqliteStore, PostgresStore)):
            raise LifecycleRejected("durable SQL store required")
        for value, minimum in ((max_active_per_owner, 1), (max_events_per_task, 3)):
            if type(value) is not int or not minimum <= value <= 10000:
                raise LifecycleRejected("invalid bounded lifecycle capacity")
        self.store = store
        self.max_active = max_active_per_owner
        self.max_events = max_events_per_task
        with self._transaction() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS task_lifecycle_snapshots ("
                "owner_id TEXT NOT NULL, task_id TEXT NOT NULL, snapshot TEXT NOT NULL,"
                "terminal INTEGER NOT NULL, PRIMARY KEY(owner_id,task_id))"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS task_lifecycle_events ("
                "owner_id TEXT NOT NULL, task_id TEXT NOT NULL, sequence BIGINT NOT NULL,"
                "snapshot TEXT NOT NULL, PRIMARY KEY(owner_id,task_id,sequence))"
            )
            if getattr(store, "tenant_id", None):
                from src.governance.tenant_store import _install_postgres_guards, _install_sqlite_guards

                tables = ("task_lifecycle_snapshots", "task_lifecycle_events")
                if isinstance(store, PostgresStore):
                    _install_postgres_guards(cur, store.schema, tables)
                else:
                    _install_sqlite_guards(cur, tables)

    @contextmanager
    def _transaction(self):
        # Reuse the governance boundary: a nested lifecycle call owns only its
        # savepoint, never the embedding admission transaction's commit.
        with sql_atomic(self.store):
            cur = self.store._db.cursor()
            try:
                if isinstance(self.store, PostgresStore):
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (911006,))
                yield cur
            finally:
                cur.close()

    def _execute(self, cur, query, values):
        if isinstance(self.store, PostgresStore):
            query = query.replace("?", "%s")
        return cur.execute(query, values)

    @staticmethod
    def _encode(task):
        return json.dumps(asdict(task), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(raw):
        data = json.loads(raw)
        data["state"] = TaskState(data["state"])
        return TaskLifecycle(**data)

    @staticmethod
    def _scope(owner_id, task_id):
        _identifier(owner_id, "authenticated owner_id")
        _identifier(task_id, "task_id")
        return owner_id, task_id

    def _get(self, cur, owner_id, task_id):
        row = self._execute(cur, "SELECT snapshot FROM task_lifecycle_snapshots "
                            "WHERE owner_id=? AND task_id=?", (owner_id, task_id)).fetchone()
        if row is None:
            raise LifecycleRejected("task unavailable for authenticated owner")
        return self._decode(row["snapshot"])

    def create(self, owner_id, task: TaskLifecycle):
        if not isinstance(task, TaskLifecycle) or task.state != TaskState.SUBMITTED or task.sequence != 0:
            raise LifecycleRejected("new task must start submitted at sequence zero")
        scope = self._scope(owner_id, task.task_id)
        with self._transaction() as cur:
            if self._execute(cur, "SELECT 1 FROM task_lifecycle_snapshots "
                             "WHERE owner_id=? AND task_id=?", scope).fetchone():
                raise LifecycleRejected("task identity already exists; no replay or replacement")
            active = self._execute(cur, "SELECT count(*) AS n FROM task_lifecycle_snapshots "
                                   "WHERE owner_id=? AND terminal=0", (owner_id,)).fetchone()["n"]
            if active >= self.max_active:
                raise LifecycleCapacity("active-task capacity reached; retry after terminal status")
            raw = self._encode(task)
            self._execute(cur, "INSERT INTO task_lifecycle_snapshots "
                          "(owner_id,task_id,snapshot,terminal) VALUES(?,?,?,0)", (*scope, raw))
            self._execute(cur, "INSERT INTO task_lifecycle_events "
                          "(owner_id,task_id,sequence,snapshot) VALUES(?,?,0,?)", (*scope, raw))
        return task

    def get(self, owner_id, task_id):
        scope = self._scope(owner_id, task_id)
        with self._transaction() as cur:
            return self._get(cur, *scope)

    def transition(self, owner_id, task_id, new_state, *, expected_sequence):
        scope = self._scope(owner_id, task_id)
        if type(expected_sequence) is not int or not 0 <= expected_sequence < 2**63 - 1:
            raise LifecycleRejected("invalid expected lifecycle sequence")
        with self._transaction() as cur:
            current = self._get(cur, *scope)
            if current.sequence != expected_sequence:
                raise LifecycleRejected("stale lifecycle sequence; reload before updating")
            updated = current.transition(new_state, sequence=current.sequence + 1)
            count = self._execute(cur, "SELECT count(*) AS n FROM task_lifecycle_events "
                                  "WHERE owner_id=? AND task_id=?", scope).fetchone()["n"]
            # Reserve the final event slot so a saturated task can still terminate.
            if count >= self.max_events or (not updated.terminal and count >= self.max_events - 1):
                raise LifecycleCapacity("task event capacity reached; terminal update required")
            raw = self._encode(updated)
            self._execute(cur, "INSERT INTO task_lifecycle_events "
                          "(owner_id,task_id,sequence,snapshot) VALUES(?,?,?,?)",
                          (*scope, updated.sequence, raw))
            self._execute(cur, "UPDATE task_lifecycle_snapshots SET snapshot=?,terminal=? "
                          "WHERE owner_id=? AND task_id=?", (raw, int(updated.terminal), *scope))
        return updated

    def cancel(self, owner_id, task_id, *, expected_sequence):
        """Record canceled status. Does not cancel transport or release a budget."""
        return self.transition(owner_id, task_id, TaskState.CANCELED, expected_sequence=expected_sequence)

    def events(self, owner_id, task_id, *, after_sequence=-1, limit=100):
        scope = self._scope(owner_id, task_id)
        if type(after_sequence) is not int or not -1 <= after_sequence < 2**63:
            raise LifecycleRejected("invalid recovery cursor")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise LifecycleRejected("event page limit must be in [1,100]")
        with self._transaction() as cur:
            current = self._get(cur, *scope)
            if after_sequence > current.sequence:
                raise LifecycleRejected("recovery cursor is ahead of durable history")
            rows = self._execute(cur, "SELECT snapshot FROM task_lifecycle_events "
                                 "WHERE owner_id=? AND task_id=? AND sequence>? "
                                 "ORDER BY sequence LIMIT ?", (*scope, after_sequence, limit)).fetchall()
            return [self._decode(row["snapshot"]) for row in rows]

    async def watch(self, owner_id, task_id, *, after_sequence=-1, page_size=16, poll_seconds=0.1):
        """Pull bounded status pages; reconnect with last consumed sequence.

        A slow reader retains at most one page. No background producer, unbounded
        queue, implicit execution, or network reconnect is created. Canceling this
        iterator has no effect on the task or its associated operation ledger.
        """
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or \
                not math.isfinite(poll_seconds) or not 0.01 <= poll_seconds <= 10:
            raise LifecycleRejected("poll interval must be finite and in [0.01,10]")
        cursor = after_sequence
        while True:
            page = await asyncio.to_thread(self.events, owner_id, task_id, after_sequence=cursor, limit=page_size)
            for task in page:
                cursor = task.sequence
                yield task
                if task.terminal:
                    return
            if not page:
                task = await asyncio.to_thread(self.get, owner_id, task_id)
                if task.terminal:
                    return
            await asyncio.sleep(poll_seconds)
