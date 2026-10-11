"""Durable anti-replay enforcement for agent-signed HTTP requests.

Production nonces use "<unix-time-seconds>:<random>" and are bound to the
request signature. Nonce claims are unique at the shared SQL store level so
independent workers cannot replay a signed request.
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from .store import SqliteStore, PostgresStore


def claim_nonce(store, agent_id: str, nonce: str, ttl_seconds: int = 300) -> bool:
    if not isinstance(store, (SqliteStore, PostgresStore)):
        raise RuntimeError("production signed requests require a shared durable SQL store")
    if not isinstance(nonce, str) or len(nonce) > 256:
        return False
    pieces = nonce.split(":", 1)
    if len(pieces) != 2 or len(pieces[1]) < 16:
        return False
    try:
        timestamp = float(pieces[0])
    except (TypeError, ValueError, OverflowError):
        return False
    now = time.time()
    if not math.isfinite(timestamp) or abs(now - timestamp) > ttl_seconds:
        return False
    cutoff = now - 2 * ttl_seconds
    if isinstance(store, SqliteStore):
        with store._lock:
            conn = store._db
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS agent_nonces ("
                    "agent_id TEXT NOT NULL, nonce TEXT NOT NULL, at REAL NOT NULL, "
                    "PRIMARY KEY (agent_id, nonce))")
                conn.execute("DELETE FROM agent_nonces WHERE at < ?", (cutoff,))
                cur = conn.execute(
                    "INSERT OR IGNORE INTO agent_nonces(agent_id,nonce,at) VALUES(?,?,?)",
                    (agent_id, nonce, now))
                conn.execute("COMMIT")
                return cur.rowcount == 1
            except BaseException:
                conn.execute("ROLLBACK")
                raise
    with store._lock, store._db.transaction(), store._db.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS agent_nonces ("
            "agent_id TEXT NOT NULL, nonce TEXT NOT NULL, at DOUBLE PRECISION NOT NULL, "
            "PRIMARY KEY (agent_id, nonce))")
        cur.execute("DELETE FROM agent_nonces WHERE at < %s", (cutoff,))
        cur.execute(
            "INSERT INTO agent_nonces(agent_id,nonce,at) VALUES(%s,%s,%s) "
            "ON CONFLICT(agent_id,nonce) DO NOTHING",
            (agent_id, nonce, now))
        return cur.rowcount == 1
