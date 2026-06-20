# AgentBridge on Kubernetes

This directory contains Kubernetes manifests for deploying AgentBridge to a cluster.

## Quick Start

```bash
# 1. Update the admin key in the Secret
kubectl apply -f k8s/deployment.yaml

# 2. Port-forward to access locally
kubectl port-forward svc/agentbridge 8000:8000

# 3. Test
curl http://localhost:8000/health
```

## Configuration

### Admin Key

The default secret uses `change-me-in-production`. You must update this before deploying to production:

```bash
kubectl create secret generic agentbridge-secrets \
  --from-literal=admin-key=$(openssl rand -hex 32) \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Database (SQLite vs Postgres)

**SQLite (default, single replica):**
The default manifest uses a `PersistentVolumeClaim` for SQLite. This only works with `replicas: 1`.

**Postgres (multi-replica):**
To run multiple instances, uncomment the Postgres section in the Secret and set:

```yaml
env:
  - name: AGENTBRIDGE_DB
    valueFrom:
      secretKeyRef:
        name: agentbridge-secrets
        key: database-url
```

Also change `replicas: 1` to `replicas: 3` (or however many you need).

### Scaling

```bash
# Scale up (only works with Postgres backend)
kubectl scale deployment agentbridge --replicas=3

# Scale down
kubectl scale deployment agentbridge --replicas=1
```

## Ingress (Production)

For production, add an Ingress or use a LoadBalancer service:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: agentbridge
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
    - hosts:
        - agentbridge.yourdomain.com
      secretName: agentbridge-tls
  rules:
    - host: agentbridge.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: agentbridge
                port:
                  number: 8000
```

## Monitoring

The deployment exposes `/health` for liveness and readiness probes. Configure your monitoring stack (Prometheus, Grafana, etc.) to scrape this endpoint.

## Troubleshooting

### Pod stuck in Pending

Check the PVC:
```bash
kubectl describe pvc agentbridge-data
```

Ensure your cluster has a default StorageClass.

### "audit chain forks" warning

This means you're running multiple replicas with SQLite. Either:
1. Set `replicas: 1`, or
2. Switch to Postgres (`AGENTBRIDGE_DB=postgresql://...`)

## See Also

- `docs/DEPLOYMENT.md` — General deployment guide
- `docs/ENTERPRISE.md` — Production governance and scaling
- `docker-compose.yml` — Docker Compose deployment (easier for local testing)
