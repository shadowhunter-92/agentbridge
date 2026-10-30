"""Destination-enforced PostgreSQL fencing and atomic signed effects.

This adapter makes the *destination itself* take a row lock on the
authoritative fence during every consequential SQL effect. A stale worker,
expired lease, changed epoch or duplicate action cannot commit here.
The fence and effect MUST live under the same single-writer PostgreSQL
authority. This does not protect unrelated remote SaaS APIs which do not
enforce the exact fence token themselves.
"""
from __future__ import annotations

import time

import psycopg
from psycopg.rows import dict_row

from .destination_receipts import canonical_receipt_payload
from .pg_fencing import _bounded_connection


class StaleDestinationLeader(RuntimeError):
    pass


class DuplicateDestinationAction(RuntimeError):
    pass


class FencedPostgresDestination:
    """Atomic destination gate for operation effect + signed receipt."""

    def __init__(self, dsn: str, *, sign):
        if not isinstance(dsn, str) or not dsn or not callable(sign):
            raise ValueError("destination writer and signer required")
        self.dsn, self.sign = dsn, sign

    def initialize(self):
        with _bounded_connection(self.dsn) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS public.ab_evidence_effects ("
                "agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, outcome TEXT NOT NULL, "
                "external_reference TEXT NOT NULL, receipt_json JSONB NOT NULL, "
                "PRIMARY KEY(agent_id,operation_id))")

    def commit(self, *, scope: str, owner: str, epoch: int,
               agent_id: str, operation_id: str, fingerprint: str,
               lose_ack: bool = False):
        if any(not isinstance(x, str) or not 1 <= len(x) <= 256
               for x in (scope, owner, agent_id, operation_id, fingerprint)):
            raise ValueError("exact destination identifiers required")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            raise ValueError("valid fencing epoch required")

        reference = "pg-fenced-effect:" + operation_id
        receipt = dict(agent_id=agent_id, operation_id=operation_id,
                       fingerprint=fingerprint, outcome="succeeded",
                       external_reference=reference)
        signed = self.sign(canonical_receipt_payload(receipt))
        if not isinstance(signed, bytes) or len(signed) != 64:
            raise ValueError("invalid destination signer")
        receipt["signature_hex"] = signed.hex()

        # The serializing lock on the authoritative fence MUST cover both
        # verification and effect write. A second leader cannot take the
        # lease while this write transaction owns the row lock.
        with _bounded_connection(self.dsn, row_factory=dict_row) as conn:
            with conn.transaction():
                locked = conn.execute(
                    "SELECT 1 FROM public.agentbridge_fences WHERE scope=%s FOR UPDATE",
                    (scope,)).fetchone()
                if locked is None:
                    raise StaleDestinationLeader("destination rejected stale or expired fence")
                # Read the database clock only after acquiring the row lock.
                # A projection evaluated before a lock wait can become stale.
                fence = conn.execute(
                    "SELECT owner,epoch,expires>clock_timestamp() AS live "
                    "FROM public.agentbridge_fences WHERE scope=%s",
                    (scope,)).fetchone()
                if (not fence or fence["owner"] != owner
                        or fence["epoch"] != epoch or not fence["live"]):
                    raise StaleDestinationLeader("destination rejected stale or expired fence")
                try:
                    conn.execute(
                        "INSERT INTO public.ab_evidence_effects "
                        "(agent_id,operation_id,fingerprint,outcome,external_reference,receipt_json) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (agent_id, operation_id, fingerprint, "succeeded",
                         reference, psycopg.types.json.Jsonb(receipt)))
                except psycopg.errors.UniqueViolation as exc:
                    raise DuplicateDestinationAction(
                        "effect already committed; no second write allowed") from exc
        if lose_ack:
            raise TimeoutError("destination commit succeeded but ACK was lost")
        return receipt
