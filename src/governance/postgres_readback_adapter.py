"""Read-only PostgreSQL system-of-record adapter for bounded action evidence.

Unlike the sandbox SQLite adapter, this reads a real PostgreSQL committed row
under a dedicated read-only SQL principal. This is one concrete database
destination type, NOT an arbitrary external SaaS system or third-party pilot.
The destination must write both the effect and signed receipt transactionally.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from .destination_receipts import UntrustedReceipt, verify_destination_receipt
from .readback_attestations import canonical_readback_payload


class PostgresReadbackUnavailable(ValueError):
    pass


def observe_postgres_effect(
    *, read_only_dsn: str, agent_id: str, operation_id: str, fingerprint: str,
    destination_public_key_hex: str, sign, source_id: str,
):
    """Query a committed effect with a separate read-only connection and key.

    Source ID identifies the operator-controlled PostgreSQL deployment and must
    not be generated from the write request. Unknown/missing/mismatch is never
    classified as failure; the caller must leave the operation UNKNOWN.
    """
    import psycopg
    from psycopg.rows import dict_row

    if any(not isinstance(v, str) or not v or len(v) > 256
           for v in (agent_id, operation_id, fingerprint)):
        raise PostgresReadbackUnavailable("operation identity required")
    if (not isinstance(source_id, str) or not source_id.startswith("postgres-readonly:")
            or len(source_id) > 256 or not callable(sign)):
        raise PostgresReadbackUnavailable("independent readback source and signer required")
    if not isinstance(read_only_dsn, str) or not read_only_dsn:
        raise PostgresReadbackUnavailable("read-only connection required")
    try:
        with psycopg.connect(read_only_dsn, connect_timeout=5, row_factory=dict_row) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    # A READ ONLY transaction alone does not establish a
                    # separately provisioned, unprivileged observer login.
                    if os.getenv("AGENTBRIDGE_ENV", "").strip().lower() in ("prod", "production"):
                        access = cur.execute(
                            "SELECT current_user = session_user, "
                            "(SELECT rolsuper OR rolcreaterole OR rolcreatedb "
                            "OR rolreplication OR rolbypassrls FROM pg_roles "
                            "WHERE rolname = current_user), "
                            "has_table_privilege(current_user, "
                            "'public.ab_evidence_effects', 'INSERT'), "
                            "has_table_privilege(current_user, "
                            "'public.ab_evidence_effects', 'UPDATE'), "
                            "has_table_privilege(current_user, "
                            "'public.ab_evidence_effects', 'DELETE'), "
                            "has_table_privilege(current_user, "
                            "'public.ab_evidence_effects', 'TRUNCATE')"
                        ).fetchone()
                        if not access or tuple(access) != (True, False, False, False, False, False):
                            raise PostgresReadbackUnavailable(
                                "production readback principal must have SELECT-only privileges")
                    cur.execute(
                        "SELECT agent_id,operation_id,fingerprint,outcome,"
                        "external_reference,receipt_json "
                        "FROM public.ab_evidence_effects WHERE agent_id=%s AND operation_id=%s",
                        (agent_id, operation_id))
                    row = cur.fetchone()
    except Exception as exc:
        raise PostgresReadbackUnavailable("authoritative database unavailable") from exc
    if not row:
        raise PostgresReadbackUnavailable("no committed effect; outcome remains unknown")
    if row["fingerprint"] != fingerprint or row["outcome"] not in ("succeeded", "failed"):
        raise PostgresReadbackUnavailable("authoritative state does not match exact operation")
    receipt = row["receipt_json"]
    if not isinstance(receipt, dict):
        raise PostgresReadbackUnavailable("persisted destination receipt missing")
    try:
        receipt_digest = verify_destination_receipt(
            receipt, agent_id=agent_id, operation_id=operation_id,
            fingerprint=fingerprint, trusted_public_key_hex=destination_public_key_hex)
    except (UntrustedReceipt, ValueError, TypeError) as exc:
        raise PostgresReadbackUnavailable("stored destination receipt untrusted") from exc
    if (receipt["outcome"] != row["outcome"]
            or receipt["external_reference"] != row["external_reference"]):
        raise PostgresReadbackUnavailable("stored receipt contradicts committed effect")
    source_evidence = hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    proof = dict(agent_id=agent_id, operation_id=operation_id, fingerprint=fingerprint,
                 outcome=row["outcome"], external_reference=row["external_reference"],
                 observed_at=int(time.time()), source=source_id,
                 source_evidence_sha256=source_evidence,
                 destination_receipt_sha256=receipt_digest)
    signature = sign(canonical_readback_payload(proof))
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise PostgresReadbackUnavailable("observer signing service unavailable")
    proof["signature_hex"] = signature.hex()
    return receipt, proof
