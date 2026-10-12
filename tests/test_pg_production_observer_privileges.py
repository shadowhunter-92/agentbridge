"""Production PostgreSQL readback must not run as a privileged writer."""
import os
import uuid
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("AGENTBRIDGE_TEST_PG"), reason="PostgreSQL service required"
)

def test_privileged_readback_login_rejected_in_production(monkeypatch):
    import psycopg
    from src.governance.postgres_readback_adapter import (
        observe_postgres_effect, PostgresReadbackUnavailable
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    dsn = os.environ["AGENTBRIDGE_TEST_PG"]
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    with pytest.raises(PostgresReadbackUnavailable):
        observe_postgres_effect(
            read_only_dsn=dsn,
            agent_id="security-check-" + uuid.uuid4().hex,
            operation_id="unknown-operation",
            fingerprint="fingerprint",
            destination_public_key_hex="00" * 32,
            source_id="postgres-readonly:CI",
            sign=Ed25519PrivateKey.generate().sign,
        )
