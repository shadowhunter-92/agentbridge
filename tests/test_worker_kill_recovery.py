"""Real process termination drill after durable claim, before target acknowledgement.

Only uses a disposable SQLite database and a local child process. The
simulation does not issue an external consequential action or test HA DB.
"""
import os
import signal
import subprocess
import sys
import pytest
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger, OperationConflict


@pytest.mark.skipif(sys.platform == "win32",reason="POSIX SIGKILL test")
def test_killed_worker_does_not_erase_unknown_operation(tmp_path):
    db=str(tmp_path/"crash.db")
    code=("import os,signal,sys;"
          "from src.governance.store import SqliteStore;"
          "from src.governance.operation_ledger import OperationLedger;"
          "s=SqliteStore(sys.argv[1]);"
          "OperationLedger(s).claim('agent','killed-operation-00001','fingerprint');"
          "os.kill(os.getpid(),signal.SIGKILL)")
    cp=subprocess.run([sys.executable,"-c",code,db],capture_output=True,timeout=20)
    assert cp.returncode == -signal.SIGKILL, cp.stderr.decode()
    store=SqliteStore(db)
    try:
        ledger=OperationLedger(store)
        assert ledger.get("agent","killed-operation-00001")["state"]=="unknown"
        with pytest.raises(OperationConflict):
            ledger.claim("agent","killed-operation-00001","fingerprint")
    finally:
        store.close()
