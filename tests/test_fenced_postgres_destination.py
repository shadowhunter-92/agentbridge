"""Real destination SQL fence gate, lost ACK and stale leader tests."""
import os
import uuid
import pytest

pytestmark=pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG"),reason="disposable PostgreSQL required")


def test_fenced_destination_rejects_stale_worker_and_recovers_lost_ack():
    import psycopg
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from src.governance.pg_fencing import PgFencing
    from src.governance.fenced_postgres_destination import (
        FencedPostgresDestination,StaleDestinationLeader,DuplicateDestinationAction)
    from src.governance.postgres_readback_adapter import observe_postgres_effect
    from src.governance.trust_sdk import verify_action_evidence

    dsn=os.environ["AGENTBRIDGE_TEST_PG"]
    stamp=uuid.uuid4().hex
    scope="destination-scope-"+stamp
    agent="fenced-agent-"+stamp
    operation="fenced-action-"+stamp
    fprint="approved-fingerprint-"+stamp
    dest_key,observer_key=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
    def pub(key):
        return key.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
    fences=PgFencing(dsn)
    fences.initialize()
    old_epoch=fences.acquire(scope,"worker-1",ttl_seconds=3)
    destination=FencedPostgresDestination(dsn,sign=dest_key.sign)
    destination.initialize()
    with pytest.raises(TimeoutError,match="ACK was lost"):
        destination.commit(scope=scope,owner="worker-1",epoch=old_epoch,
                           agent_id=agent,operation_id=operation,
                           fingerprint=fprint,lose_ack=True)
    receipt,readback=observe_postgres_effect(
        read_only_dsn=dsn,agent_id=agent,operation_id=operation,
        fingerprint=fprint,destination_public_key_hex=pub(dest_key),
        sign=observer_key.sign,source_id="postgres-readonly:isolated-ci")
    assert verify_action_evidence(
        destination_receipt=receipt,readback_attestation=readback,
        agent_id=agent,operation_id=operation,fingerprint=fprint,
        outcome="succeeded",external_reference="pg-fenced-effect:"+operation,
        destination_key_hex=pub(dest_key),readback_key_hex=pub(observer_key)).outcome=="succeeded"
    with pytest.raises(DuplicateDestinationAction):
        destination.commit(scope=scope,owner="worker-1",epoch=old_epoch,
                           agent_id=agent,operation_id=operation,fingerprint=fprint)
    import time
    time.sleep(3.2)
    new_epoch=fences.acquire(scope,"worker-2",ttl_seconds=20)
    assert new_epoch>old_epoch
    with pytest.raises(StaleDestinationLeader):
        destination.commit(scope=scope,owner="worker-1",epoch=old_epoch,
                           agent_id=agent,operation_id="old-worker-"+stamp,
                           fingerprint=fprint)
    success=destination.commit(scope=scope,owner="worker-2",epoch=new_epoch,
                               agent_id=agent,operation_id="new-worker-"+stamp,
                               fingerprint=fprint)
    assert success["outcome"]=="succeeded"
    with psycopg.connect(dsn) as conn:
        count=conn.execute("SELECT count(*) FROM ab_evidence_effects WHERE agent_id=%s",(agent,)).fetchone()[0]
        assert count==2
