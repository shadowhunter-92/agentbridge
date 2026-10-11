import pytest
from src.governance.store import SqliteStore
from src.governance.audit_trust import AuditTrustStore, AuditTrustError
from src.governance.audit import AuditLog
from src.governance.identity import AgentIdentity


def test_legal_hold_survives_across_independent_workers(tmp_path):
    path=str(tmp_path/"holds.db")
    a,b=SqliteStore(path),SqliteStore(path)
    try:
        first,second=AuditTrustStore(a),AuditTrustStore(b)
        first.set_hold("litigation-case",True)
        assert second.holds()==["litigation-case"]
        second.set_hold("litigation-case",False)
        assert first.holds()==[]
        log=AuditLog(a)
        log.record(actor="a",action="route_call",source_protocol="mcp",
                   target_protocol="a2a",capability="read",decision="allow")
        signer=AgentIdentity.generate("signer")
        checkpoint=log.checkpoint(signer.sign,signer.public_key_hex)
        with pytest.raises(AuditTrustError):
            first.save_checkpoint(checkpoint,"0"*64)
        assert first.save_checkpoint(checkpoint,signer.public_key_hex)==1
        with pytest.raises(Exception):
            second.save_checkpoint(checkpoint,signer.public_key_hex)
    finally:
        a.close()
        b.close()
