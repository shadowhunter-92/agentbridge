#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence
kubectl create namespace agentbridge --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f deploy/kubernetes/networkpolicy.review.yaml
cat > /tmp/agentbridge-network-acceptance.yaml <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentbridge-acceptance-targets
  namespace: agentbridge
spec:
  replicas: 1
  selector:
    matchLabels:
      app: agentbridge-acceptance-targets
  template:
    metadata:
      labels:
        app: agentbridge-acceptance-targets
        app.kubernetes.io/name: agentbridge-egress
    spec:
      containers:
        - name: target
          image: python:3.12-alpine
          command: ["python","-m","http.server","3128","--bind","0.0.0.0"]
          ports: [{containerPort: 3128}]
---
apiVersion: v1
kind: Service
metadata:
  name: allowed-proxy
  namespace: agentbridge
spec:
  selector: {app: agentbridge-acceptance-targets}
  ports: [{port: 3128, targetPort: 3128}]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: forbidden-test-target
  namespace: agentbridge
spec:
  replicas: 1
  selector:
    matchLabels: {app: forbidden-test-target}
  template:
    metadata:
      labels: {app: forbidden-test-target}
    spec:
      containers:
        - name: target
          image: python:3.12-alpine
          command: ["python","-m","http.server","8080","--bind","0.0.0.0"]
          ports: [{containerPort: 8080}]
---
apiVersion: v1
kind: Service
metadata:
  name: forbidden-target
  namespace: agentbridge
spec:
  selector: {app: forbidden-test-target}
  ports: [{port: 8080, targetPort: 8080}]
---
apiVersion: v1
kind: Pod
metadata:
  name: restricted-worker
  namespace: agentbridge
  labels:
    app.kubernetes.io/name: agentbridge-worker
spec:
  containers:
    - name: python
      image: python:3.12-alpine
      command: ["sleep","900"]
---
apiVersion: v1
kind: Pod
metadata:
  name: unselected-control
  namespace: agentbridge
spec:
  containers:
    - name: python
      image: python:3.12-alpine
      command: ["sleep","900"]
YAML
kubectl apply -f /tmp/agentbridge-network-acceptance.yaml
kubectl -n agentbridge rollout status deployment/agentbridge-acceptance-targets --timeout=180s
kubectl -n agentbridge rollout status deployment/forbidden-test-target --timeout=180s
kubectl -n agentbridge wait pod/restricted-worker pod/unselected-control --for=condition=Ready --timeout=180s

probe() {
  local pod="$1" host="$2" port="$3" expected="$4" name="$5"
  local status
  if kubectl -n agentbridge exec "$pod" -- python -c 'import socket,sys; c=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3);c.close()' "$host" "$port" > /tmp/probe.out 2>&1; then
    status="allow"
  else
    status="deny"
  fi
  printf '%s,%s,%s,%s,%s,%s\n' "$name" "$pod" "$host" "$port" "$expected" "$status" | tee -a evidence/network-results.csv
  if [ "$status" != "$expected" ]; then
    cat /tmp/probe.out
    echo "FAIL: $name expected $expected got $status" >&2
    return 1
  fi
}
printf 'test,pod,host,port,expected,observed\n' > evidence/network-results.csv
# The control connection must first become available before we attribute
# subsequent negative results to policy enforcement, rather than boot races.
ready=0
for attempt in $(seq 1 18); do
  if kubectl -n agentbridge exec unselected-control -- python -c 'import socket;socket.create_connection(("forbidden-target",8080),timeout=2).close()' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ "$ready" != "1" ]; then
  echo "FAIL: control service never became reachable" >&2
  exit 1
fi
probe unselected-control forbidden-target 8080 allow control_can_reach_forbidden
probe restricted-worker allowed-proxy 3128 allow worker_can_reach_allowlisted_proxy
probe restricted-worker forbidden-target 8080 deny worker_cannot_reach_other_destination
probe restricted-worker allowed-proxy 8080 deny worker_cannot_use_unallowlisted_port
probe restricted-worker 169.254.169.254 80 deny worker_cannot_reach_metadata_ipv4
probe restricted-worker 1.1.1.1 443 deny worker_cannot_bypass_egress_proxy
# This is a disposable network-layer check, not workload-authenticated mTLS.
kubectl -n agentbridge get networkpolicies -o yaml > evidence/applied-policies.yaml
echo 'Calico kind enforcement checks passed for this disposable cluster'
