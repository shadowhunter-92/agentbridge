# AWS PostgreSQL operational experiment — 2026-10-13

**Classification:** executed AWS-hosted *partial acceptance tests*, not production
HA, independently administered readback, generic fencing, end-to-end
application upgrade, or the complete P0–P2 gate.

## Environment and safeguards

- AWS Free plan ACTIVE; Free Tier API reported USD 140 available credits
  before and after the experiment (not a settled cost or invoice).
- Two disposable Amazon Linux 2023 EC2 `t3.small` nodes in `us-east-1`.
- 8-GiB encrypted gp3 boot disk, IMDSv2 required, no SSH ingress.
- Security group restricted inbound TCP/5432 to members of the same
  temporary group; outbound restricted to HTTPS and same-group PostgreSQL.
- Separate ephemeral instance profile carrying only SSM managed instance
  permissions. Instances configured to terminate upon a 35-minute shutdown;
  explicitly terminated at the end.
- PostgreSQL 16.15 installed on both nodes through AWS Systems Manager.
- Single-authority SQL tests were performed on one node; **physical
  standby replication and dual-node takeover were not configured**.

## Observed results

| Test | Observation | Qualification |
| --- | --- | --- |
| Both PostgreSQL hosts initialized | PostgreSQL 16.15, `pg_is_in_recovery() = false` | PASS: independently started database instances, not replicated HA |
| Local least-privilege observer | Dedicated OS/database observer could SELECT evidence table | PASS: local permission separation, **not independently administered custody** |
| Observer cannot modify evidence | Observer INSERT failed `permission denied for table effects` | PASS: write privilege was denied for tested table |
| Synthetic stale epoch | Epoch changed from 1 to 2; conditional INSERT using epoch 1 affected 0 rows | PASS: illustrative SQL predicate; **not an atomic destination-enforced authorization function or stale-leader process race** |
| Evidence retention through schema change | Added `release_version` column, read original effect, dropped column, reread original effect | PASS: reversible SQL schema demo, **not full application rollback** |
| Backup and restore | `pg_dump -Fc` and `pg_restore` to separate disposable database; restored `op-1|succeeded` | PASS: one synthetic logical backup/restore |
| Local PostgreSQL service restart | Measured 405 ms wall-clock to ready after clean `systemctl restart` | OBSERVATION only: neither failover RTO nor crash recovery RPO |
| Lost acknowledgement | Not injected on AWS hosts | OPEN |
| Stale leader across separate processes/hosts | Not exercised with destination-atomic fencing | OPEN |
| Physical replica promotion | Not deployed or exercised | OPEN |
| Independently operated signing/readback | Not provisioned | OPEN |

**Execution limitation:** the attempted full two-node configuration using
replication credentials was blocked by the execution service. That attempt
did not apply. A narrower credential-free local test was executed instead;
do not interpret it as a workaround satisfying the distributed acceptance
criteria.

## Teardown and billing safety

Explicit EC2 termination was performed for both hosts. Subsequent
`DescribeInstances` reported each as `terminated`. The temporary
security group, IAM role, IAM instance profile and attached managed policy
were removed successfully. Follow-up inventory found zero active
AgentBridge-tagged EC2 instances, zero AgentBridge security groups and zero
tagged EBS volumes. Monthly USD 5 budget alert remains in place.

The Free Tier API still showed USD 140, but AWS usage and credits can post
after the experiment. **No zero-dollar finalized invoice is claimed.**

## Next P0–P2 acceptance work

1. Implement/test an operation-bound destination-atomic fencing adapter under
   two separate authenticated client processes/hosts, with post-handover old
   leader rejection and lost-ACK authoritative reconciliation.
2. Deploy a separately administered read-only observer/signing principal and
   qualify key lifecycle, independent evidence retrieval and rotation.
3. Provision approved replica topology with automated controlled election and
   fencing; measure crash/partition recovery RPO and RTO over repeated trials.
4. Test actual application artifact upgrade/rollback with pinned versions,
   migrations and external-effect/audit continuity.
5. Preserve logs and artifact digests with an independent reviewer sign-off.

**Release posture:** engineering alpha; unrestricted production NO-GO.
