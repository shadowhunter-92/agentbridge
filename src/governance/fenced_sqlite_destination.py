"""Experimental non-PostgreSQL destination with destination-side fencing.

A local SQLite *destination* serializes epoch validation and action insertion
in ONE BEGIN IMMEDIATE transaction. This does not fence an arbitrary SaaS API,
a replicated SQLite volume, or a target that does not call this destination.
Use only for disposable/supervised demonstrations.
"""
from __future__ import annotations

import json
import sqlite3

from .destination_receipts import canonical_receipt_payload


class SqliteFenceDenied(RuntimeError):
    """Lease is owned elsewhere, expired, or epoch no longer authoritative."""


class SqliteDuplicateEffect(RuntimeError):
    """An operation already reached the destination; never dispatch it again."""


def _identifier(value):
    return isinstance(value, str) and 1 <= len(value) <= 128


class FencedSqliteTarget:
    def __init__(self, path: str, *, sign):
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("single durable disposable SQLite destination required")
        if not callable(sign):
            raise ValueError("destination-controlled signing callback required")
        self.sign = sign
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sqlite_destination_fences "
            "(scope TEXT PRIMARY KEY, owner TEXT NOT NULL, epoch INTEGER NOT NULL, "
            "expires_seconds INTEGER NOT NULL)"
        )
        # Reuse the sandbox observer's read-only, signed readback contract.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sandbox_effects "
            "(agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
            "fingerprint TEXT NOT NULL, outcome TEXT NOT NULL, "
            "external_reference TEXT NOT NULL, receipt_json TEXT NOT NULL, "
            "PRIMARY KEY(agent_id,operation_id))"
        )

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def acquire(self, *, scope: str, owner: str, ttl_seconds: int = 15) -> int:
        if not _identifier(scope) or not _identifier(owner):
            raise ValueError("bounded scope and owner required")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("bounded integer TTL required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            now = self.db.execute("SELECT CAST(strftime('%s','now') AS INTEGER)").fetchone()[0]
            row = self.db.execute(
                "SELECT epoch,expires_seconds FROM sqlite_destination_fences WHERE scope=?",
                (scope,),
            ).fetchone()
            if row is not None and row["expires_seconds"] > now:
                raise SqliteFenceDenied("an authoritative destination owner is already live")
            epoch = (row["epoch"] + 1) if row else 1
            self.db.execute(
                "INSERT INTO sqlite_destination_fences(scope,owner,epoch,expires_seconds) "
                "VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET "
                "owner=excluded.owner,epoch=excluded.epoch,"
                "expires_seconds=excluded.expires_seconds",
                (scope, owner, epoch, now + ttl_seconds),
            )
            self.db.execute("COMMIT")
            return epoch
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def commit(
        self, *, scope: str, owner: str, epoch: int,
        agent_id: str, operation_id: str, fingerprint: str,
        lose_ack: bool = False,
    ):
        if not all(_identifier(x) for x in (scope, owner, agent_id, operation_id, fingerprint)):
            raise ValueError("exact bounded operation identity required")
        if type(epoch) is not int or epoch < 1:
            raise ValueError("valid monotonic destination epoch required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT owner,epoch,expires_seconds, "
                "CAST(strftime('%s','now') AS INTEGER) AS now_seconds "
                "FROM sqlite_destination_fences WHERE scope=?",
                (scope,),
            ).fetchone()
            if (row is None or row["owner"] != owner or row["epoch"] != epoch
                    or row["expires_seconds"] <= row["now_seconds"]):
                raise SqliteFenceDenied("stale, expired or unauthorized destination epoch")
            if self.db.execute(
                "SELECT 1 FROM sandbox_effects WHERE agent_id=? AND operation_id=?",
                (agent_id, operation_id),
            ).fetchone():
                raise SqliteDuplicateEffect("operation was already executed at the destination")
            receipt = {
                "agent_id": agent_id,
                "operation_id": operation_id,
                "fingerprint": fingerprint,
                "outcome": "succeeded",
                "external_reference": "sqlite-fenced-effect:" + operation_id,
            }
            signature = self.sign(canonical_receipt_payload(receipt))
            if not isinstance(signature, bytes) or len(signature) != 64:
                raise ValueError("destination signature invalid")
            receipt["signature_hex"] = signature.hex()
            self.db.execute(
                "INSERT INTO sandbox_effects VALUES(?,?,?,?,?,?)",
                (agent_id, operation_id, fingerprint, "succeeded",
                 receipt["external_reference"],
                 json.dumps(receipt, sort_keys=True, separators=(",", ":"))),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        if lose_ack:
            raise TimeoutError("committed SQLite destination effect; acknowledgement dropped")
        return receipt
