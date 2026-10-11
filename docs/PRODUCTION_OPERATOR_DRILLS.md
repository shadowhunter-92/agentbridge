# AgentBridge supervised staging and failure-injection checklist

**Status: procedure drafted; not yet executed on independent managed infrastructure.**

Use a disposable, isolated environment with synthetic data and a nonproduction PostgreSQL database. Obtain operator authorization before any destructive drill. Never perform failure injection against customer infrastructure.

## Preconditions and hard gates

- Deploy from an immutable commit SHA with a repeatable container/SBOM and automated dependency scanning.
- Use a dedicated PostgreSQL database with backups enabled and a dedicated minimal-privilege service account.
- Terminate TLS at a trusted boundary, restrict egress, pin allowed destinations, prohibit untrusted stdio commands, and require operator-controlled agent and capability ACLs.
- Set stable production signing/admin secrets through a secret manager. No test credentials, ephemeral keys or default secrets.
- Require explicit operation IDs for every consequential action, with remote-system idempotency support where possible.
- Set up OpenTelemetry, error budgets, audit integrity alarms, clock synchronization and ready/liveness health probes.
- Confirm cryptographic test identities, fake target agents and all traffic are confined to staging.

## Staging drill matrix (record measured evidence)

| ID | Drill | Expected outcome | Evidence required |
|---|---|---|---|
| S1 | Wrong/missing/expired signed proof | HTTP reject; no external target call | Request trace, target call count zero |
| S2 | Unknown agent and revoked key while a second worker remains alive | Reject on both workers | DB revocation record, two-worker log |
| S3 | Request for nonallowlisted tool or destination | Deny before invocation | Policy reason and zero side effects |
| S4 | Simultaneously retry same operation ID from multiple replicas | One claim maximum; never execute twice | DB ledger, traces, target receipts |
| S5 | Drop connection after remote target commits | Mark outcome unknown; no automatic retry | Target idempotency log, ledger, audit record |
| S6 | Kill worker at each stage: before claim, after claim, during network call, after response before commit | No duplicate execution; ambiguous stages require reconciliation | DB snapshots, failover traces |
| S7 | Partition Postgres and recover | Fail closed for new privileged operations | Timeline, error rates, recovery log |
| S8 | Concurrent approval submit/consume/revoke on separate replicas | Only approved exact request executes once | Approval rows and invocation counts |
| S9 | Inject audit entry tampering and mismatched checkpoint signer | Offline verification refuses | Trusted-key verification report |
| S10 | Restore DB snapshot and compare with externally preserved signed head | Detect rollback; do not silently certify missing records | Backups and signed checkpoints |
| S11 | Rotate signing keys, IdP JWKS, admin keys and credentials | Old revoked credentials fail; live traffic drains safely | Rotation ledger and traces |
| S12 | 1h/24h replay and load tests at target concurrency | Meet measured p95/p99 and error SLOs without forks | Load artifacts, latency distribution |

## Evidence pack for each drill

Capture git SHA, container digest, dependency lockfile, environment without secrets, timestamp, topology, database/version, inputs, expected results, observed results, logs, audit export, operation ledger, owner approval, independent reviewer signature, and explicit pass/fail disposition.

## Release decision

A staging run is not a penetration test or certification. The release requires every in-scope drill to pass, independent security evaluation, operation reconciliation procedures, and explicit operator sign-off. Production audit retention stays disabled until durable legal holds and externally anchored checkpoints exist.

## Roadmap beyond initial release

R4: SDK and three outside integrations. R5: evidence-backed paid design-partner pilot. R6: HA managed deployments, long-term support, repeatability and customer retention. R7: interoperability and standards participation, only after external adoption.