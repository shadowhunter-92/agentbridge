"""Disposable actual Docker TCP partition between a PostgreSQL client and server.

No host ports, no real databases. The client loses its only Docker network,
cannot contact its PostgreSQL server, then is reconnected. The committed
unknown operation survives and a same-ID insert cannot replay. This is NOT
distributed leader-election or two-writable-primary split-brain simulation.
"""
import json
import os
import subprocess
import time
import uuid


def _run(args,check=True,timeout=25):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"{args[:4]}: {p.stderr[-800:]}")
    return p


def main():
    if os.getenv("AGENTBRIDGE_DISPOSABLE_NETWORK_PARTITION")!="1":
        raise RuntimeError("destructive Docker partition drill requires explicit test opt-in")
    uid=uuid.uuid4().hex[:12]
    net="ab-partition-"+uid
    server="ab-partition-db-"+uid
    client="ab-partition-client-"+uid
    password="disposable-partition-"+uid
    created=[]
    result={}
    try:
        _run(["docker","network","create",net])
        created.append(("network",net))
        _run(["docker","run","-d","--name",server,"--network",net,
              "--network-alias","ab-db","-e","POSTGRES_PASSWORD="+password,
              "postgres:16"])
        created.append(("container",server))
        _run(["docker","run","-d","--name",client,"--network",net,
              "-e","PGPASSWORD="+password,"-e","PGCONNECT_TIMEOUT=2",
              "postgres:16","sleep","3600"])
        created.append(("container",client))
        psql=["docker","exec",client,"psql","-X","-h","ab-db","-U","postgres",
              "-d","postgres","-At","-c"]
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if _run(psql+["SELECT 1"],check=False,timeout=8).returncode==0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("test PostgreSQL never became reachable")
        _run(psql+["CREATE TABLE partition_unknown (operation_id TEXT PRIMARY KEY, state TEXT NOT NULL); "
                   "INSERT INTO partition_unknown VALUES ('action-1','unknown')"])
        _run(["docker","network","disconnect","--force",net,client])
        failed=_run(psql+["SELECT state FROM partition_unknown"],check=False,timeout=10)
        assert failed.returncode!=0,"worker unexpectedly accessed PostgreSQL while partitioned"
        _run(["docker","network","connect",net,client])
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            restored=_run(psql+["SELECT state FROM partition_unknown"],check=False,timeout=8)
            if restored.returncode==0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("worker failed to recover after network reconnect")
        assert restored.stdout.strip()=="unknown"
        duplicate=_run(psql+["INSERT INTO partition_unknown VALUES ('action-1','unknown')"],
                       check=False,timeout=8)
        assert duplicate.returncode!=0,"duplicate operation unexpectedly inserted"
        result={
            "kind":"disposable-postgres-container-network-disconnect",
            "worker_unreachable_during_partition":True,
            "unknown_action_survived_reconnect":True,
            "duplicate_id_rejected":True,
            "limitations":"No two-primary partition, distributed witness, elected leader or RPO/RTO",
        }
        print(json.dumps(result,indent=2))
        if os.getenv("AGENTBRIDGE_NETWORK_PARTITION_REPORT"):
            with open(os.environ["AGENTBRIDGE_NETWORK_PARTITION_REPORT"],"w") as f:
                json.dump(result,f,indent=2)
    finally:
        for kind,name in reversed(created):
            if kind=="container":
                _run(["docker","rm","-f",name],check=False)
            else:
                _run(["docker","network","rm",name],check=False)


if __name__=="__main__":
    main()
