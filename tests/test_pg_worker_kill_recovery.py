"""Worker SIGKILL and persistent operation guard on disposable PostgreSQL."""
import os
import signal
import subprocess
import sys
import uuid
import pytest

@pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG") or sys.platform=="win32",
                    reason="requires disposable Postgres and POSIX")
def test_postgres_recover_after_worker_sigkill():
    from src.governance.store import PostgresStore
    from src.governance.operation_ledger import OperationLedger, OperationConflict
    dsn=os.environ["AGENTBRIDGE_TEST_PG"]
    agent="killtest-"+uuid.uuid4().hex
    operation="op-"+uuid.uuid4().hex
    script=("import os,sys,signal;"
            "from src.governance.store import PostgresStore;"
            "from src.governance.operation_ledger import OperationLedger;"
            "s=PostgresStore(os.environ['AGENTBRIDGE_TEST_PG']);"
            "OperationLedger(s).claim(sys.argv[1],sys.argv[2],'fingerprint');"
            "os.kill(os.getpid(),signal.SIGKILL)")
    done=subprocess.run([sys.executable,"-c",script,agent,operation],
                        capture_output=True,timeout=20)
    assert done.returncode==-signal.SIGKILL,done.stderr.decode()
    store=PostgresStore(dsn)
    try:
        ledger=OperationLedger(store)
        assert ledger.get(agent,operation)["state"]=="unknown"
        with pytest.raises(OperationConflict):
            ledger.claim(agent,operation,"fingerprint")
    finally:
        store.close()
