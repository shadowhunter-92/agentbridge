# AgentBridge egress release review: verified tests vs production gaps

## Evidence completed in October 2026 on PR #34

- `docker-compose.egress-drill.yml`: disposable Docker **internal**
  worker network with the worker connected only to `sealed`. The separate
  CONNECT proxy has `sealed` and `outbound` network attachments.
- `tools/egress_docker_probe.py`: opens sockets from the **worker**
  to public addresses, metadata service, and DNS-by-IP; must see direct access
  fail. Confirms worker can reach the proxy and that it denies unlisted and
  numeric-IP CONNECT destinations.
- GitHub Actions `egress-isolation-drill` executes the actual disposable
  two-container deployment and probe. This is not only static policy inspection.
- `deploy/kubernetes/networkpolicy.review.yaml` documents namespace/pod
  selectors and explicit outbound worker paths (proxy TCP3128, Postgres
  TCP5432, cluster DNS TCP/UDP53) plus inbound proxy scoping. The YAML is
  a **review specimen**; it has not been applied or observed in a cluster.

## What is NOT proven

- Host/CNI implementation, rootless/container escape boundaries, alternate
  interfaces, DNS tunneling, sidecar/shared-namespace escape, IPv6 routing
  or policy operation under node/cluster upgrades.
- DB transport authentication, proxy workload identity, mTLS, per-agent proxy
  authorization, TLS SNI vs CONNECT authority, certificate validation across
  redirects, management-plane and secrets access.
- Cross-host or multi-zone HA routing; externally operated target traffic.
- No user-facing production process should mount the Docker socket or gain
  `NET_ADMIN`/`SYS_ADMIN` capabilities.

## Operator acceptance drill (requires real infrastructure)

1. Deploy the worker, database and proxy into an isolated test Kubernetes
   namespace and confirm actual Pod labels and namespace selectors.
2. Confirm CNI supports NetworkPolicy and denies worker direct IPv4 and IPv6
   internet, metadata, link-local and other namespace destinations.
3. Verify only proxy and required DB/DNS traffic passes; reject unlisted
   host, untrusted DNS reply, IP literal, unauthorized CONNECT and redirect.
4. Verify proxy only accepts authenticated worker identity in the production
   design, and logs destination/address decisions to separate retention.
5. Test non-HTTP tools, subprocesses, DNS rebinding and the actual TLS client.
6. Record node/CNI versions, routes, packet-policy decisions, timestamps,
   test artifacts, operator signature and reviewer result.

Release classification: **disposable Docker acceptance proved in CI**,
**Kubernetes policy authored/tested structurally**, **actual production
network isolation not accepted**.
