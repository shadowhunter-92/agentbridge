# AWS two-host PostgreSQL qualification — 13 October 2026

**Classification:** EXECUTED two-host AWS engineering acceptance; **NOT** unrestricted production approval, third-party destination safety, automatic HA, independent organizational key custody, or multi-trial RPO/RTO SLO qualification.

## Reproducibility and provenance

- Execution environment: two temporary Amazon Linux 2023 `t3.small` EC2 hosts in `us-east-1`; PostgreSQL 16 physical primary/standby; Python 3.11; pinned AgentBridge source.
- Application baseline: `397b94030c093c7694ae18547bf796362c70e24e`.
- Candidate used for distributed adapter tests: `d0a84fae32592f2bad6117a9b305d44d3ef77726` (initial primary installation used `31d323c22c4f8806104fb101352bbb623e80c12f` with the same tested adapter).
- Executed harness: `tools/aws_pg_two_host_acceptance.sh` (with bootstrap fixes over commits `8b2ed82`, `a68c53c`, `2c0220d`, `31d323c`, `d0a84fa`); `tools/aws_pg_upgrade_rollback.sh` (`36da007c`).
- CI validation on `36da007c`: full CI #431, Kubernetes CNI acceptance #38, AWS offline preflight #26, two-host harness static check #12 all **passed**. This confirms repository tests, not the independent operational acceptance.

## Provisioning and credential boundaries

- Separate EC2 instance identities; scoped IAM access only to SSM Parameter Store namespace `/agentbridge/ephemeral-20261013/` for two temporary replication/writer SecureStrings.
- Replication and writer passwords were generated on the primary and sent to Parameter Store as `SecureString`, then retrieved by the standby. **No database password was placed literally in the SSM RunCommand text or committed to Git.**
- The standby held the replay-only password in a PostgreSQL-owned, `0600` `.pgpass`. Both secrets were deleted after the run.
- Network: no inbound SSH; PostgreSQL TCP/5432 allowed solely within the two-host security group; outbound HTTPS plus same-group PostgreSQL. Encrypted 8-GiB instance storage; IMDSv2 required; 35-minute self-termination policy.
- The observer's Ed25519 private key was generated on the standby host and never transmitted to GitHub or the primary. **Both instances were still administered through the same AWS account and tooling**; separate-host technical separation is **not** independent organizational custody.
- PostgreSQL readback operated as the separate `abobserver` role; unprivileged SELECT succeeded and a DELETE attempt was denied. The signed observer file was validated via `openssl pkeyutl -verify`. This is a signature over an observed receipt snapshot, not the full separately administered canonical readback attestation or independent source-of-truth sign-off.
- Destination Ed25519 signing key for the original synthetic action was generated in the caller process and was not retained as a pinned independent trust root. **Consequently this run did not independently revalidate the original destination receipt signature after the action; it validated the observer's signed snapshot and exact persisted record.**

## Executed action-authorization and recovery tests

| Check | Observed result | Meaning |
| --- | --- | --- |
| Primary PostgreSQL initialized | `PRIMARY_READY` (the first bootstrap revealed AL2023 default Python 3.9 and venv permissions; fixes applied and primary initialization finished) | AWS-hosted destination, pinned project code, real database |
| Separate physical standby | `STANDBY_REPLAYING` and `pg_is_in_recovery()=true` | PostgreSQL WAL-streaming recovery, not merely two independent DBs |
| Original worker | `OLD_LEADER_EPOCH 1` | Obtained authoritative epoch |
| Replacement worker from different host | `NEW_EPOCH 2 LOST_ACK_DETECTED DUPLICATE_DENIED EFFECTS 1` | **Actual `PgFencing` and `FencedPostgresDestination` adapter** ran via separate host connection; write committed despite dropped ACK, duplicate prevented |
| Resumed old worker | `STALE_OLD_LEADER_DENIED` | Old worker could not commit after higher epoch |
| Observer readback and signing | `READBACK_READONLY_OBSERVER_SIGNATURE_VERIFIED`, SHA256 `3567f576cbaa73aad925139f7c9ff161e76f3e5569872ed257032e6813076700` | Separate PostgreSQL role and signed snapshot; observer write denied |
| Physical WAL evidence | `REPLICATED_EFFECT_PRESENT`, replay LSN `0/3000868` | Intended synthetic action visibly present on hot standby before promotion |
| Old primary stopped | `PRIMARY_STOPPED` at Unix timestamp `1791884822.513931860` | Explicit operator source-fencing before promotion |
| Standby promoted | `PHYSICAL_REPLICA_PROMOTED`, SQL query returned `once|succeeded` at `1791884863.877405208` | Promoted standby preserved the committed effect |
| Local promote-to-SQL | `PROMOTE_TO_SQL_MS=143` | One local operation measurement |
| Stop-to-SQL observable recovery | **41.36 seconds** from primary stop to successful post-promotion SQL in two separately invoked SSM commands | End-to-end test timing including substantial manual/SSM scheduling, not automated HA RTO |
| Tested data loss | One confirmed action persisted after promotion, zero missing among this **one** sampled operation | Cannot establish RPO for all writes, lag states or failures |

The original primary was deliberately stopped before promotion. **This experiment did not permit two concurrently writable primaries, test uncontrolled split-brain, or demonstrate automatic external leader fencing.** No production RPO/RTO SLO is accepted from a single sample.

## Executed application-artifact upgrade and rollback

The promoted host built two distinct wheels from pinned Git commits; the Python package still reports version `1.0.0` for both, so **the commit and wheel digests**, not the package version alone, distinguish them.

| Artifact | SHA256 |
| --- | --- |
| Baseline wheel | `0ff031fc33071a6f3f51ff72f707c89dcc5947ec6c9541bc2f70084cbd41b5e0` |
| Candidate wheel | `aec7a50d69f3217c23c4d1456af9e3d85e4bf49454e7041692fa4c8106506dcc` |

Sequence: install baseline wheel → verify evidence and installed package import → install candidate wheel → verify evidence and import → reinstall baseline wheel → verify evidence and import.

Observed after **each** transition: `EVIDENCE_SIGNATURE_AND_SINGLE_EFFECT_PRESERVED`, then `APPLICATION_ARTIFACT_UPGRADE_ROLLBACK_ACCEPTED`. This demonstrates rollback of tested Python wheel artifacts and preservation of an existing signed observer record and exactly one persisted effect.

**Limitations:** no two-version live service traffic, external customer system, approval state migration across incompatible schemas, independent artifact publisher/key custody, or measured zero-downtime rolling deployment. Neither wheel was a signed public registry release.

## AWS resource teardown and costs

- Both EC2 instances `i-0735d2a8843d8d513` and `i-0137c5d8d92618acf`: **terminated**, independently verified through EC2 inventory.
- Temporary security group `sg-0bce750ff03f41aa1`: deleted.
- Temporary IAM role, attached SSM policy, inline Parameter Store policy and instance profile: deleted.
- Temporary `replication` and `writer` Parameter Store SecureStrings: deleted and absent in follow-up inventory.
- Follow-up inventory: **0 active AgentBridge-tagged instances, 0 AgentBridge security groups, 0 tagged EBS volumes, 0 temporary lab parameters**.
- AWS Free plan remained `ACTIVE`, credits reported `$140` after the test; delayed billing may change the balance. Budget alert is not an absolute cap. No claim of a final zero-dollar invoice.

## Acceptance classification

| Requested milestone | Status |
| --- | --- |
| Two-host physical replication and controlled failover | **Demonstrated** for deliberately source-fenced, single-destination PostgreSQL; automated failover, partition and split-brain **open** |
| Real AgentBridge stale-leader and lost-ACK rejection across hosts | **Demonstrated** for PostgreSQL adapter, single-authority destination |
| Separately permissioned readback and Ed25519 signature on different host | **Demonstrated** technically; independent organization/operator-controlled custody and official canonical attestation trust **open** |
| Application artifact upgrade/rollback with retained signed observer evidence | **Demonstrated** in a synthetic, controlled wheel-swap test; production migrations and rolling upgrade acceptance **open** |

**Release decision:** scoped engineering alpha **BUILD / INVESTIGATE**, unrestricted consequential-action production **NO-GO** until outstanding destination, custody, split-brain, publishing and external review gates are accepted.
