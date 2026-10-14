# Enforced egress reference and next production blocking gates

## Implemented on PR #34

The minimal `src.proxy.restricted_connect` service implements an HTTP CONNECT
relay bound to loopback. It admits only configured, exact DNS hostnames on
port 443; rejects arbitrary methods and malformed authority; resolves DNS
before connecting; rejects mixed private/public, loopback, link-local,
reserved, and non-global addresses; and connects to an authorized **numeric IP**
so DNS is not silently re-resolved during the socket connection.

Tests in `tests/test_egress_policy.py` and
`tests/test_restricted_connect_network.py` check malicious authorities,
forbidden ports, DNS rebinding mixtures and live socket-level denials.

**This does not enforce the worker's network perimeter.** A compromised worker
can still open direct sockets unless the actual deployment prevents it.
The bounded loopback relay is a reference prototype, **not** an independently
security-reviewed production proxy. It has no proxy authentication, per-agent
quotas or mTLS, no TLS inspection, limited telemetry, and no deployed firewall.
No outbound positive-path customer interoperability has been claimed.

## True network release gate (internal implementation + operated test)

1. Choose and document a target deployment (Kubernetes or Docker host).
2. Put the worker in an egress-denied network namespace; allow only specifically
   authorized database, DNS and proxy destinations. Never attach a shared
   unrestricted bridge to the worker.
3. Deploy the egress gateway in a separate namespace/host trust boundary,
   with strictly scoped CONNECT destinations, source identity and operator policy.
4. Independently probe worker direct TCP, DNS rebinding, cross-network redirects,
   malicious CONNECT, metadata endpoints, IPv4+IPv6 and non-HTTP stdio subprocesses.
5. Check TLS end-to-end hostname verification in the actual client, collect
   packet/network policy decisions, then subject the deployment to review.

Network policy and operational evidence must come from the real deployment.
Application-level URL checking alone never closes this gate.

## Work remaining in dependency order

| Priority | Our engineering still needed | External/operated validation |
|---|---|---|
| P0 | Real target readback adapter, independent credential/key administration, reviewer roles | Third-party target access and signed review |
| P1 | Egress-denied workload deploy specification and adversarial runtime tests | Managed firewall/network operator |
| P2 | PostgreSQL partition/failover, PITR restore, migration/rollback tooling | HA infrastructure and witnessed drills |
| P3 | Precise supported MCP/A2A SDK feature matrices and negative interoperability | External reference implementations |
| P4 | Lockfiles, SBOM and CVE scan, signed release and upgrade/rollback | Release signing keys and trusted distribution |
| P5 | Sustained load, failure budgets and repeatable SLO test harness | Real target capacity/workload acceptance |
| P6 | OSS documentation, installable SDK reference examples, partner outreach | Independent integrations, paid pilot |

Release decision: **NOT production-ready**, and PR #34 stays draft until
all applicable production gates and independent approvals are satisfied.
