"""Separate-state audit witness journal for a bounded verification deployment.

The database backing this journal MUST be controlled independently of the
AgentBridge application/database. SQLite is provided for reproducible testing
and low-volume pilot deployments, not an immutable external archive.
Journal rollback and operator/key compromise require independent WORM anchoring.
"""
from __future__ import annotations

import json
import sqlite3
import threading

from .external_anchor import (
    AnchorVerificationError, checkpoint_digest, verify_anchored_audit,
)


class WitnessJournal:
    """Accept only monotonic, chain-consistent third-party witness receipts."""

    def __init__(self, path: str, *, checkpoint_key_hex: str, witness_key_hex: str,
                 witness_id: str):
        if not path or path == ":memory:" or not isinstance(path, str):
            raise AnchorVerificationError("durable witness journal path required")
        if not isinstance(witness_id, str) or not witness_id:
            raise AnchorVerificationError("witness identity required")
        self._checkpoint_key = checkpoint_key_hex
        self._witness_key = witness_key_hex
        self._witness_id = witness_id
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, timeout=10, isolation_level=None,
                                   check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.execute("CREATE TABLE IF NOT EXISTS witness_journal("
                         "witness_id TEXT NOT NULL, seq INTEGER NOT NULL,"
                         "checkpoint_digest TEXT NOT NULL, head_hash TEXT NOT NULL,"
                         "checkpoint TEXT NOT NULL, receipt TEXT NOT NULL,"
                         "PRIMARY KEY(witness_id,seq))")

    def close(self):
        self._db.close()

    def latest(self):
        with self._lock:
            row = self._db.execute(
                "SELECT checkpoint,receipt FROM witness_journal "
                "WHERE witness_id=? ORDER BY seq DESC LIMIT 1",
                (self._witness_id,)).fetchone()
            if not row:
                return None
            return {"checkpoint": json.loads(row["checkpoint"]),
                    "witness": json.loads(row["receipt"])}

    def accept(self, records: list, checkpoint: dict, witness: dict):
        """Fail closed on stale, forked, replayed or inconsistent checkpoint history.

        An exact duplicate is idempotent, not a second witness entry. Callers
        must separately authenticate the journal endpoint and ensure that
        journal storage cannot be rolled back by the governed application.
        """
        summary = verify_anchored_audit(
            records, checkpoint, witness,
            checkpoint_key_hex=self._checkpoint_key, witness_key_hex=self._witness_key)
        if witness["witness_id"] != self._witness_id:
            raise AnchorVerificationError("witness identity not pinned")
        seq = summary["witnessed_sequence"]
        digest = checkpoint_digest(checkpoint)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                prior = self._db.execute(
                    "SELECT seq,checkpoint_digest,head_hash FROM witness_journal "
                    "WHERE witness_id=? ORDER BY seq DESC LIMIT 1",
                    (self._witness_id,)).fetchone()
                if prior:
                    if seq < prior["seq"]:
                        raise AnchorVerificationError("rollback behind journal head")
                    if seq == prior["seq"]:
                        if digest != prior["checkpoint_digest"]:
                            raise AnchorVerificationError("conflicting checkpoint at same sequence")
                        self._db.execute("COMMIT")
                        return {"accepted": True, "duplicate": True, "seq": seq}
                    # Verify the newly supplied COMPLETE history retains the
                    # previous journal head before accepting the new checkpoint.
                    if prior["seq"] > len(records):
                        raise AnchorVerificationError("history truncated before prior witness")
                    previous_hash = ("0" * 64 if prior["seq"] == 0
                                     else records[prior["seq"] - 1]["entry_hash"])
                    if previous_hash != prior["head_hash"]:
                        raise AnchorVerificationError("fork detected against previous witness")
                self._db.execute(
                    "INSERT INTO witness_journal VALUES(?,?,?,?,?,?)",
                    (self._witness_id, seq, digest, summary["head_hash"],
                     json.dumps(checkpoint, sort_keys=True),
                     json.dumps(witness, sort_keys=True)))
                self._db.execute("COMMIT")
                return {"accepted": True, "duplicate": False, "seq": seq}
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
