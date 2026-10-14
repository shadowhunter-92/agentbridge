# Kubernetes evaluation reference

These manifests are for isolated synthetic evaluation, not production acceptance.
Provision `agentbridge-secrets` separately in the same namespace before applying
`deployment.yaml`; no administrator key is shipped. Use your secret manager or
a private local key file, and keep secret values out of shell history and Git.

```bash
kubectl create secret generic agentbridge-secrets --from-file=admin-key=/private/operator-key
kubectl apply -f k8s/deployment.yaml
kubectl port-forward svc/agentbridge 8000:8000
```

The single replica stores SQLite at `/app/data/governance.db` on PVC
`agentbridge-data`. Supply a tested PostgreSQL backend before multi-node scaling.
Liveness uses `/health`, readiness uses `/ready`, and metrics are at `/metrics`.
The image tag is an evaluation reference; qualify an immutable reviewed digest
before any deployment acceptance.

The separate `deploy/kubernetes/networkpolicy.review.yaml` is a worker/proxy
topology specimen in namespace `agentbridge`. It selects
`app.kubernetes.io/name: agentbridge-worker`, while this HTTP deployment uses
`app: agentbridge`. They are different roles and do not automatically compose.
Do not relabel the control plane as a worker without reviewing its IdP, database
and outbound traffic. Reconcile namespaces/selectors and prove enforcement with
an enforcing CNI and the actual workload before claiming egress isolation.

See [deployment](../docs/DEPLOYMENT.md), [acceptance register](../docs/CURRENT_STATUS_2026-10-13.md)
and [egress criteria](../docs/EGRESS_DEPLOYMENT_VERIFICATION.md).
