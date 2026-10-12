"""Actual disposable PostgreSQL WAL archive point-in-time recovery drill.

Creates uniquely named local Docker volumes and containers, then deletes them.
Restores a physical base backup to a named restore point preceding a synthetic
later write. Does not access a production DSN or run managed cloud PITR.
"""
import json
import os
import subprocess
import time
import uuid


def run(args,*,check=True,timeout=90):
    proc=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError(f"{args[:5]} failed: {proc.stderr[-1100:]}")
    return proc


def probe(container,query,*,password,port):
    return run(["docker","exec","-e","PGPASSWORD="+password,container,
                "psql","-X","-h","127.0.0.1","-p",str(port),
                "-U","postgres","-d","postgres","-At","-c",query],
               check=False,timeout=12)


def ready(container,password,port,*,deadline=75):
    end=time.monotonic()+deadline
    while time.monotonic()<end:
        r=probe(container,"SELECT 1",password=password,port=port)
        if r.returncode==0 and r.stdout.strip()=="1":
            return
        time.sleep(1)
    raise RuntimeError("disposable PostgreSQL never became ready")


def drill():
    if os.getenv("AGENTBRIDGE_DISPOSABLE_PITR_DRILL")!="1":
        raise RuntimeError("PITR requires explicit disposable opt-in")
    stamp=uuid.uuid4().hex[:12]
    primary="ab-pitr-primary-"+stamp
    target="ab-pitr-target-"+stamp
    backup="ab-pitr-backup-"+stamp
    archive="ab-pitr-wal-"+stamp
    primarydata="ab-pitr-data-"+stamp
    restoreddata="ab-pitr-restored-"+stamp
    secret="disposable-pitr-"+stamp
    original_port,restored_port=55537,55538
    created=[]
    start=time.monotonic()
    try:
        for name in (backup,archive,primarydata,restoreddata):
            run(["docker","volume","create",name])
            created.append(("volume",name))
        run(["docker","run","--rm","-v",archive+":/archive","--user","0",
             "postgres:16","chown","-R","postgres:postgres","/archive"])
        run(["docker","run","-d","--name",primary,"--network","host",
             "-v",primarydata+":/var/lib/postgresql/data",
             "-v",archive+":/archive",
             "-e","POSTGRES_PASSWORD="+secret,"postgres:16",
             "postgres","-c","port="+str(original_port),
             "-c","wal_level=replica","-c","archive_mode=on",
             "-c","archive_command=cp %p /archive/%f"])
        created.append(("container",primary))
        ready(primary,secret,original_port)
        assert probe(primary,
          "CREATE TABLE pitr_proof(id TEXT PRIMARY KEY); "
          "INSERT INTO pitr_proof VALUES ('before-snapshot')",
          password=secret,port=original_port).returncode==0
        run(["docker","run","--rm","--network","host",
             "-v",backup+":/backup","-e","PGPASSWORD="+secret,
             "postgres:16","pg_basebackup","-h","127.0.0.1","-p",str(original_port),
             "-U","postgres","-D","/backup/base","-X","stream","-c","fast",
             "--no-password"],timeout=150)
        restorepoint=probe(primary,
            "SELECT pg_create_restore_point('before_later_write')",
            password=secret,port=original_port)
        assert restorepoint.returncode==0
        assert probe(primary,
            "INSERT INTO pitr_proof VALUES ('after-restore-point')",
            password=secret,port=original_port).returncode==0
        assert probe(primary,"SELECT pg_switch_wal()",password=secret,
                     port=original_port).returncode==0
        time.sleep(3)
        run(["docker","stop","--time","5",primary],timeout=30)
        # Copy a physical base backup to an isolated second PGDATA volume.
        run(["docker","run","--rm","--user","0",
             "-v",backup+":/backup",
             "-v",restoreddata+":/var/lib/postgresql/data",
             "postgres:16","bash","-c",
             "cp -a /backup/base/. /var/lib/postgresql/data/ && "
             "touch /var/lib/postgresql/data/recovery.signal && "
             "printf \"\\nrestore_command = 'cp /archive/%f %p'\\n"
             "recovery_target_name = 'before_later_write'\\n"
             "recovery_target_action = 'promote'\\n\" >> "
             "/var/lib/postgresql/data/postgresql.auto.conf && "
             "chown -R postgres:postgres /var/lib/postgresql/data"],timeout=120)
        run(["docker","run","-d","--name",target,"--network","host",
             "-v",restoreddata+":/var/lib/postgresql/data",
             "-v",archive+":/archive",
             "-e","POSTGRES_PASSWORD="+secret,
             "postgres:16","postgres","-c","port="+str(restored_port)])
        created.append(("container",target))
        ready(target,secret,restored_port)
        end=time.monotonic()+45
        while time.monotonic()<end:
            value=probe(target,"SELECT pg_is_in_recovery()",password=secret,
                        port=restored_port)
            if value.returncode==0 and value.stdout.strip()=="f":
                break
            time.sleep(.5)
        else:
            raise AssertionError("PITR did not promote after named recovery point")
        rows=probe(target,"SELECT id FROM pitr_proof ORDER BY id",
                   password=secret,port=restored_port)
        assert rows.returncode==0,rows.stderr
        assert rows.stdout.strip()=="before-snapshot",rows.stdout
        return {
            "kind":"disposable-postgresql16-wal-archive-named-point-in-time-restore",
            "pre_snapshot_row_preserved":True,
            "post_restore_point_write_excluded":True,
            "promotion_verified":True,
            "elapsed_seconds":round(time.monotonic()-start,3),
            "limitations":"Single-host disposable WAL archive; no continuous backups, cloud provider, customer RPO/RTO or multi-zone failure",
        }
    finally:
        for kind,name in reversed(created):
            if kind=="container":
                run(["docker","rm","-f",name],check=False)
            else:
                run(["docker","volume","rm","-f",name],check=False)


if __name__=="__main__":
    result=drill()
    dest=os.getenv("AGENTBRIDGE_PITR_DRILL_REPORT")
    if dest:
        with open(dest,"w") as stream:
            json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))
