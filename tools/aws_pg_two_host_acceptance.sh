#!/usr/bin/env bash
# Disposable two-host PostgreSQL qualification. No database password literals.
# SSM RunCommand sends only the phase, IPs, parameter namespace and pinned SHA.
set -euo pipefail
umask 077
mode="$1"
: "$AB_LAB_PREFIX"
: "$AB_PRIMARY_IP"
: "$AB_STANDBY_IP"
: "$AB_SOURCE_SHA"
root=/opt/agentbridge-qualification
mkdir -p "$root" /opt/ab-logs
  chmod 755 "$root"
cd "$root"
export AWS_DEFAULT_REGION=us-east-1
fetch_secret() {
  aws ssm get-parameter --name "$AB_LAB_PREFIX/$1" --with-decryption \
    --query Parameter.Value --output text
}
store_secret() {
  aws ssm put-parameter --name "$AB_LAB_PREFIX/$1" --type SecureString \
    --value "$2" --overwrite >/dev/null
}
setup_source() {
  dnf -y install postgresql16-server postgresql16 postgresql16-contrib git python3.11 python3.11-pip openssl >/opt/ab-logs/packages.log 2>&1
  python3.11 -m venv "$root/venv"
  "$root/venv/bin/pip" -q install "psycopg[binary]" cryptography >/opt/ab-logs/python.log 2>&1
  if [ ! -d "$root/source/.git" ]; then git clone -q https://github.com/shadowhunter-92/agentbridge.git "$root/source"; fi
  cd "$root/source"
  git fetch -q origin integration/r4-main-reconciliation-2026-10
  git checkout -q "$AB_SOURCE_SHA"
  test "$(git rev-parse HEAD)" = "$AB_SOURCE_SHA"
  "$root/venv/bin/pip" -q install -e "$root/source" >>/opt/ab-logs/python.log 2>&1
  chmod -R a+rX "$root/venv" "$root/source"
  echo "SOURCE_PIN_VERIFIED=$AB_SOURCE_SHA"
}
admin() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -X "$@"; }
case "$mode" in
  primary-init)
    setup_source
    if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then postgresql-setup --initdb >/opt/ab-logs/initdb.log 2>&1; fi
    openssl req -x509 -nodes -newkey rsa:3072 -days 1 \
      -subj "/CN=agentbridge-lab" \
      -keyout /var/lib/pgsql/data/server.key -out /var/lib/pgsql/data/server.crt \
      >/opt/ab-logs/tls.log 2>&1
    chown postgres:postgres /var/lib/pgsql/data/server.*
    chmod 600 /var/lib/pgsql/data/server.key
    cat >>/var/lib/pgsql/data/postgresql.conf <<CONF

listen_addresses = '*'
ssl = on
wal_level = replica
max_wal_senders = 5
hot_standby = on
synchronous_commit = on
CONF
    cat >>/var/lib/pgsql/data/pg_hba.conf <<CONF

hostssl replication abreplica $AB_STANDBY_IP/32 scram-sha-256
hostssl agentbridge_test abwriter $AB_STANDBY_IP/32 scram-sha-256
CONF
    systemctl enable --now postgresql
    for role in abreplica abwriter; do
      secret="$(openssl rand -hex 32)"
      if [ "$role" = "abreplica" ]; then
        store_secret replication "$secret"
        printf "CREATE ROLE abreplica LOGIN REPLICATION PASSWORD '%s';\n" "$secret" | admin -q >/dev/null
      else
        store_secret writer "$secret"
        printf "CREATE ROLE abwriter LOGIN PASSWORD '%s';\n" "$secret" | admin -q >/dev/null
      fi
      unset secret
    done
    admin -q -c 'CREATE ROLE abobserver LOGIN;'
    admin -q -c 'CREATE DATABASE agentbridge_test;'
    cd "$root/source"
    runuser -u postgres -- "$root/venv/bin/python" -c 'from src.governance.pg_fencing import PgFencing; from src.governance.fenced_postgres_destination import FencedPostgresDestination; PgFencing("dbname=agentbridge_test user=postgres").initialize(); FencedPostgresDestination("dbname=agentbridge_test user=postgres",sign=lambda _:bytes(64)).initialize()'
    admin -q -d agentbridge_test -c 'REVOKE ALL ON agentbridge_fences,ab_evidence_effects FROM PUBLIC;'
    admin -q -d agentbridge_test -c 'GRANT SELECT,INSERT,UPDATE ON agentbridge_fences TO abwriter;'
    admin -q -d agentbridge_test -c 'GRANT SELECT,INSERT ON ab_evidence_effects TO abwriter;'
    admin -q -d agentbridge_test -c 'GRANT SELECT ON ab_evidence_effects TO abobserver;'
    admin -q -c 'GRANT CONNECT ON DATABASE agentbridge_test TO abwriter,abobserver;'
    admin -q -d agentbridge_test -c 'GRANT USAGE ON SCHEMA public TO abwriter,abobserver;'
    echo PRIMARY_READY
    ;;
  standby-init)
    setup_source
    replication_secret="$(fetch_secret replication)"
    install -m 600 -o postgres -g postgres /dev/null /var/lib/pgsql/.pgpass
    printf "%s:5432:replication:abreplica:%s\\n" "$AB_PRIMARY_IP" "$replication_secret" > /var/lib/pgsql/.pgpass
    chown postgres:postgres /var/lib/pgsql/.pgpass
    chmod 600 /var/lib/pgsql/.pgpass
    export PGPASSFILE=/var/lib/pgsql/.pgpass
    install -d -o postgres -g postgres -m 700 /var/lib/pgsql/data
    runuser -u postgres -- pg_basebackup \
      -d "host=$AB_PRIMARY_IP port=5432 user=abreplica sslmode=require" \
      -D /var/lib/pgsql/data -R -X stream -P >/opt/ab-logs/basebackup.log 2>&1
    unset replication_secret PGPASSFILE
    systemctl enable --now postgresql
    runuser -u postgres -- psql -X -tAc 'SELECT pg_is_in_recovery();' | grep -qx t
    useradd -r -s /bin/bash abobserver || true
    install -d -m 700 "$root/observer"
    openssl genpkey -algorithm ED25519 -out "$root/observer/private.pem"
    openssl pkey -in "$root/observer/private.pem" -pubout -out "$root/observer/public.pem"
    chmod 600 "$root/observer/private.pem"
    echo STANDBY_REPLAYING
    ;;
  old-leader)
    cd "$root/source"
    runuser -u postgres -- "$root/venv/bin/python" - <<'PY'
from src.governance.pg_fencing import PgFencing
epoch=PgFencing("dbname=agentbridge_test user=postgres").acquire("aws-lab","old-worker",ttl_seconds=1.5)
assert epoch==1,epoch
print("OLD_LEADER_EPOCH",epoch)
PY
    ;;
  new-leader)
    export PGPASSWORD="$(fetch_secret writer)"
    cd "$root/source"
    "$root/venv/bin/python" - <<'PY'
import os,time,psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src.governance.pg_fencing import PgFencing,FenceDenied
from src.governance.fenced_postgres_destination import FencedPostgresDestination,DuplicateDestinationAction
dsn="host="+os.environ["AB_PRIMARY_IP"]+" dbname=agentbridge_test user=abwriter sslmode=require"
f=PgFencing(dsn)
for _ in range(50):
    try:epoch=f.acquire("aws-lab","new-worker",ttl_seconds=90);break
    except FenceDenied:time.sleep(.2)
else:raise AssertionError("new epoch not acquired")
assert epoch==2,epoch
d=FencedPostgresDestination(dsn,sign=Ed25519PrivateKey.generate().sign)
try:
    d.commit(scope="aws-lab",owner="new-worker",epoch=epoch,
        agent_id="aws-test",operation_id="once",fingerprint="synthetic",lose_ack=True)
except TimeoutError as e:assert "ACK was lost" in str(e)
else:raise AssertionError("lost ACK injection failed")
try:
    d.commit(scope="aws-lab",owner="new-worker",epoch=epoch,
        agent_id="aws-test",operation_id="once",fingerprint="synthetic")
except DuplicateDestinationAction:pass
else:raise AssertionError("duplicate side effect permitted")
with psycopg.connect(dsn) as conn:
    count=conn.execute("SELECT count(*) FROM ab_evidence_effects WHERE operation_id='once'").fetchone()[0]
assert count==1,count
print("NEW_EPOCH",epoch,"LOST_ACK_DETECTED","DUPLICATE_DENIED","EFFECTS",count)
PY
    unset PGPASSWORD
    ;;
  reject-old)
    cd "$root/source"
    runuser -u postgres -- "$root/venv/bin/python" - <<'PY'
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src.governance.fenced_postgres_destination import FencedPostgresDestination,StaleDestinationLeader
try:
    FencedPostgresDestination("dbname=agentbridge_test user=postgres",
        sign=Ed25519PrivateKey.generate().sign).commit(
        scope="aws-lab",owner="old-worker",epoch=1,agent_id="aws-test",
        operation_id="stale",fingerprint="synthetic")
except StaleDestinationLeader:print("STALE_OLD_LEADER_DENIED")
else:raise AssertionError("stale leader committed")
PY
    ;;
  observe)
    runuser -u abobserver -- psql -X -d agentbridge_test -tAc \
      "SELECT count(*) FROM ab_evidence_effects WHERE operation_id='once';" | grep -qx 1
    if runuser -u abobserver -- psql -v ON_ERROR_STOP=1 -d agentbridge_test -c \
      "DELETE FROM ab_evidence_effects WHERE operation_id='once';" > /opt/ab-logs/observer_denied.log 2>&1; then
      echo UNSAFE_OBSERVER_WRITE;exit 1
    fi
    runuser -u abobserver -- psql -XAt -d agentbridge_test -c \
      "SELECT receipt_json FROM ab_evidence_effects WHERE operation_id='once';" \
      > "$root/observer/receipt.json"
    openssl pkeyutl -sign -rawin -inkey "$root/observer/private.pem" \
      -in "$root/observer/receipt.json" -out "$root/observer/receipt.sig"
    openssl pkeyutl -verify -rawin -pubin -inkey "$root/observer/public.pem" \
      -in "$root/observer/receipt.json" -sigfile "$root/observer/receipt.sig" >/dev/null
    sha256sum "$root/observer/receipt.json"
    echo READBACK_READONLY_OBSERVER_SIGNATURE_VERIFIED
    ;;
  replica-check)
    runuser -u postgres -- psql -d agentbridge_test -tAc \
      "SELECT count(*) FROM ab_evidence_effects WHERE operation_id='once';" | grep -qx 1
    runuser -u postgres -- psql -XAt -c 'SELECT pg_last_wal_replay_lsn();'
    echo REPLICATED_EFFECT_PRESENT
    ;;
  stop-primary)
    systemctl stop postgresql
    if runuser -u postgres -- pg_isready -q; then echo PRIMARY_STILL_UP;exit 1;fi
    echo PRIMARY_STOPPED
    ;;
  promote)
    start="$(date +%s%3N)"
    runuser -u postgres -- pg_ctl promote -D /var/lib/pgsql/data -w -t 40 \
      > /opt/ab-logs/promote.log 2>&1
    test "$(runuser -u postgres -- psql -tAc 'SELECT pg_is_in_recovery();')" = f
    runuser -u postgres -- psql -d agentbridge_test -XAt -c \
      "SELECT operation_id,outcome FROM ab_evidence_effects ORDER BY operation_id;"
    finish="$(date +%s%3N)"
    echo "PROMOTE_TO_SQL_MS=$((finish-start))"
    echo PHYSICAL_REPLICA_PROMOTED
    ;;
  *) echo "Unknown phase" >&2; exit 2;;
esac
