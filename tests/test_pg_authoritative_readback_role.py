"""Real PostgreSQL role-isolated destination readback, lost ACK, tamper denial."""
import json
import os
import uuid
import pytest

pytestmark=pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG"),reason="disposable PostgreSQL required")


def test_postgres_observer_reads_committed_effect_without_write_privileges():
    import psycopg
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from src.governance.destination_receipts import canonical_receipt_payload
    from src.governance.postgres_readback_adapter import observe_postgres_effect,PostgresReadbackUnavailable
    from src.governance.trust_sdk import verify_action_evidence
    from psycopg.conninfo import make_conninfo

    dsn=os.environ["AGENTBRIDGE_TEST_PG"]
    suffix=uuid.uuid4().hex[:16]
    role="ab_observer_"+suffix
    observer_password="disposable-observer-"+suffix
    agent,operation,fingerprint="agent-"+suffix,"operation-"+suffix,"request-"+suffix
    destination,observer=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
    def pub(k):
        return k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
    receipt=dict(agent_id=agent,operation_id=operation,fingerprint=fingerprint,
                 outcome="succeeded",external_reference="pg-effect:"+suffix)
    receipt["signature_hex"]=destination.sign(canonical_receipt_payload(receipt)).hex()
    # Disposable CI principal owns this schema. The observer is created with
    # SELECT only; no table owner, no superuser or broad public privileges.
    from psycopg import sql
    with psycopg.connect(dsn,autocommit=True) as admin:
        try:
            admin.execute("CREATE TABLE IF NOT EXISTS public.ab_evidence_effects "
                          "(agent_id TEXT,operation_id TEXT,fingerprint TEXT,outcome TEXT,"
                          "external_reference TEXT,receipt_json JSONB,"
                          "PRIMARY KEY(agent_id,operation_id))")
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role),sql.Literal(observer_password)))
            admin.execute(sql.SQL("GRANT SELECT ON public.ab_evidence_effects TO {}").format(sql.Identifier(role)))
            admin.execute("INSERT INTO public.ab_evidence_effects VALUES (%s,%s,%s,%s,%s,%s)",
                          (agent,operation,fingerprint,"succeeded",receipt["external_reference"],json.dumps(receipt)))
            ro_dsn=make_conninfo(dsn,user=role,password=observer_password)
            returned,proof=observe_postgres_effect(
                read_only_dsn=ro_dsn,agent_id=agent,operation_id=operation,
                fingerprint=fingerprint,destination_public_key_hex=pub(destination),
                sign=observer.sign,source_id="postgres-readonly:disposable-test")
            assert verify_action_evidence(
                destination_receipt=returned,readback_attestation=proof,
                agent_id=agent,operation_id=operation,fingerprint=fingerprint,
                outcome="succeeded",external_reference=receipt["external_reference"],
                destination_key_hex=pub(destination),readback_key_hex=pub(observer)).outcome=="succeeded"
            with psycopg.connect(ro_dsn) as unprivileged:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    unprivileged.execute("DELETE FROM public.ab_evidence_effects")
            with pytest.raises(PostgresReadbackUnavailable):
                observe_postgres_effect(read_only_dsn=ro_dsn,agent_id=agent,
                                        operation_id="missing",fingerprint=fingerprint,
                                        destination_public_key_hex=pub(destination),
                                        sign=observer.sign,source_id="postgres-readonly:disposable-test")
            admin.execute("UPDATE public.ab_evidence_effects SET outcome='failed' "
                          "WHERE agent_id=%s AND operation_id=%s",(agent,operation))
            with pytest.raises(PostgresReadbackUnavailable):
                observe_postgres_effect(read_only_dsn=ro_dsn,agent_id=agent,
                                        operation_id=operation,fingerprint=fingerprint,
                                        destination_public_key_hex=pub(destination),
                                        sign=observer.sign,source_id="postgres-readonly:disposable-test")
        finally:
            admin.execute("DELETE FROM public.ab_evidence_effects WHERE agent_id=%s AND operation_id=%s",
                          (agent,operation))
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
