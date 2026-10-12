# Production completion contract — internal engineering vs independent acceptance

**Release status: NO-GO.** This register is a falsifiable checklist for all
six requested workstreams. The internal deliverables are **our** work, even
when obtaining a separate system or test environment is inconvenient.

| Workstream | Completed internal evidence | Remaining OUR work | Genuine outside dependency |
|---|---|---|---|
| Authoritative readback | Sandbox signed receipts, read-only observer, signed operator settlement, fixed-origin HTTPS readback adapter | Consent-ready destination-specific read-only connector and auth enrollment, separate signer deployment, source-of-truth/outcome semantics, lost ACK/revocation/key-rotation tests | Target owner permits a scoped read-only credential; independent trust administration and review |
| PostgreSQL recovery | Isolated pg_dump/restore, backend termination, fenced streaming standby/promotion | Disconnected-network partition tests, lease/fencing split-brain defense, automated promotion with documented RPO/RTO, schema migration reversibility and PITR drill | Real managed HA environment/operational acceptance |
| Network security | Sealed Docker worker/proxy drill, pinned resolved global IPs, Kubernetes policy specimen, IPv6 parsing tests | mTLS/SPIFFE-equivalent workload identity, destination TLS/SNI verification strategy, no direct worker egress in real CNI, policy logging/quotas, redirect/DNS/IPv6 runtime probes | Deployment owner and professional security review of actual network and host |
| Supply chain | Wheel clean install, CycloneDX Python environment inventory, advisory scan gate, signed-manifest **verifier** | Base image digest pinning, lock files and hashes, complete container SBOM/scanning, builder provenance, publisher-controlled manifest signing, upgrade/revert rehearsals | Independent signing custody, trusted publication channel and security acceptance |
| Interoperability | SDK-shape tests and declared 6x6 narrow tool-call matrix | MCP/A2A transport/auth/error/cancel/lifecycle matrix for pinned versions; fail-closed unsupported features; official reference tests | Independent third-party reference implementers and integration feedback |
| Performance | Synthetic SQL 250 actions/8 workers with p50/p95/p99 and bounded accounting | Sustained representative mixes, load shedding, resource metrics, chaos tests, stated error/latency budgets, reproducible thresholds | Realistic workloads, production SLO negotiation, external pilot |

## Production gate requirements

- Go only if the target owner independently confirms observation semantics
  and a separately administered verifier signs evidence from true read-only
  authoritative data; no user-supplied receipt alone constitutes proof.
- Go only when workload identity and TLS destination policy are enforced
  on the deployment network; the Python reference proxy remains sandbox-only.
- Go only after an independently controlled witness retains append-only
  checkpoints and older snapshots cannot roll back authoritative trust state.
- Go only after PostgreSQL network partitions, failover fencing, PITR,
  upgrades and rollback tests are passing in an operated staging system.
- Go only after protocol claims are restricted to passing version-specific
  reference suites, and release artifacts are reproducible, signed and
  security reviewed, with observable operational SLOs.
- Obtain independent security review and a consented bounded pilot before
  unsupervised consequential actions.

## Current work product

`src/governance/https_readback_adapter.py` and
`tests/test_https_readback_adapter.py` add and exercise a fixed-origin
HTTPS GET and an independently keyed signed observation **contract**.
This is not a deployed integration to a named customer or provider, and the
destination must independently operate a legitimate source-of-truth API.
TLS alone is not egress isolation; customer semantics and key custody remain
separate acceptance conditions.

The four planned offerings (OSS, Trust, Evidence, Enterprise) share the same
kernel; Enterprise is not a second cryptographic implementation. Independently
evaluating the OSS SDK and developing an Enterprise business case are separate
commercial objectives, not proof of security certification.

## Review update — verified TLS SNI guard (October 12)

`src/proxy/tls_sni_guard.py` now strictly parses an initial, complete
bounded TLS ClientHello and the disposable CONNECT relay refuses SNI differing
from the configured/allowed CONNECT authority. Missing/opaque ECH, multiple
SNI identities, truncated/malformed TLS records fail closed.
`tests/test_tls_sni_guard.py` checks these invariants and CI #285 ran all
six GitHub Actions jobs successfully.

**This is not an authenticated production proxy.** The reference only
accepts a single-record ClientHello, cannot inspect encrypted SNI/ECH,
does not authenticate a target certificate on behalf of the client,
does not replace tenant-aware workload authentication and cannot prove
that a compromised caller cannot bypass proxy networking. A production
candidate needs a separate reviewed gateway deployment and end-to-end
certificate/hostname verification by the real TLS client.

### Explicit internal blocker burn-down: no phantom completions

- Real target's operator-controlled read-only identity and signing service:
  PostgreSQL and generic fixed-origin HTTPS prototypes are passing;
  independent operation, key rotation and real source-of-truth semantics OPEN.
- PostgreSQL: disposable dump/restore and manually fenced standby pass;
  PITR, partition, automated election/lease fencing, audited RPO/RTO OPEN.
- Release: clean wheel, CycloneDX Python inventory, advisory scan,
  signed-manifest verification pass; dependency hash-lock, entire image
  attestations, container scan and *actual* signed artifact OPEN.
- MCP/A2A: narrow official SDK shape checks pass; transport/session/version
  conformance and reference matrix OPEN.
- Performance: bounded SQL concurrency passes; sustained saturation,
  resource budgets and production-representative SLO OPEN.
- Adoption: OSS evaluation kit written; three independent integrations,
  security review and authorized paying pilot NOT demonstrated.

**Release verdict remains NO-GO.** Do not close these gates by changing labels
or relying solely on passing unit tests.
