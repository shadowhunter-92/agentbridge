# Real AWS staging qualification — 2026-10-13

**Evidence status:** AWS API and SSM command execution, bounded runtime test,
terminated resources. This is a **real, single-node AWS-hosted Kubernetes test**,
NOT a multi-node production qualification or sign-off for consequential writes.

## Account and budget constraints

- AWS Free Tier API reported **FREE / ACTIVE**, initially USD 100 promotional
  credits. A later read returned USD 140 (pending separate credit-grant/billing
  reconciliation). Promotional credits are not a hard cost cap or settled bill.
- A monthly USD 5 AWS Budget was configured; **AWS Budgets is alerting, not
  hard cost enforcement**. No paid-plan upgrade was performed.
- Region: `us-east-1`. No customer data, AWS production secrets, external
  target credentials, SSH ingress or public application endpoint used.

## Actual infrastructure and tests

- Temporary `t3.small` Amazon Linux 2023 EC2 host with encrypted 8 GiB
  gp3 volume, public address required for SSM network reachability and
  no inbound security-group rules.
- Outbound EC2 security-group policy restricted to HTTPS TCP/443.
- Temporary instance profile had AWS-managed
  `AmazonSSMManagedInstanceCore` and no other IAM policy.
- Instance metadata IMDSv2 required: unauthenticated metadata HTTP returned
  `401`; token request returned `200`.
- Host was configured with a forty-minute shutdown plus EC2
  `InstanceInitiatedShutdownBehavior=terminate` fail-safe. Explicit
  termination was requested well before timeout.
- SSM installed K3s `v1.36.5+k3s1` (one control-plane node, running CoreDNS);
  `kubectl wait nodes --for=Ready` passed.
- Applied repository Kubernetes NetworkPolicy and test harness from pinned
  commit `0d2232ade436ad86ccede04deecf51a144bc204a`. All six observed
  expectations matched:
  1. Unselected control Pod -> forbidden service TCP/8080: **ALLOW**
  2. Selected worker -> allowed proxy TCP/3128: **ALLOW**
  3. Selected worker -> forbidden service TCP/8080: **DENY**
  4. Selected worker -> wrong proxy port TCP/8080: **DENY**
  5. Selected worker -> metadata IPv4 TCP/80: **DENY**
  6. Selected worker -> direct public IPv4 TCP/443: **DENY**

The harness prints the string `Calico kind enforcement checks passed` in
its final echo, but **this AWS test used K3s network-policy enforcement, NOT
Calico/kind**. Calico/kind had separately passed on GitHub Actions runners.
The result must be described by its actual test environment.

## Confirmed cleanup

AWS `TerminateInstances` completed and `DescribeInstances` returned
`terminated`. The temporary security group was deleted. The IAM instance
profile was detached and deleted, the SSM managed role policy detached, and
the temporary role deleted. Subsequent EC2 inventory found **zero active
AgentBridge-tagged instances, zero AgentBridge security groups and zero
tagged EBS volumes**. The USD 5 monthly budget remains as a cost warning.
AWS metering and credit consumption may post later; no zero-cost invoice
can be claimed solely from the current remaining-credit response.

## P0/P1/P2 conclusion

**P0 partial operational evidence gained:** real AWS EC2 host and single-node
K3s network-policy isolation, remote SSM management, IMDSv2 and cleanup.
**Still OPEN:** independently administered observer and signing authority,
real third-party destination fencing, workload-authenticated mTLS / SPIFFE,
IPv6 and DNS bypass and multi-node cloud CNI enforcement.

**P1 still OPEN:** two-node controlled failover/split-brain, measured production
RPO/RTO, independently signed/publicly verifiable artifacts and application
upgrade/rollback in operated staging.

**P2 still OPEN:** complete pinned official MCP/A2A reference transport tests,
full end-to-end production-shaped latency and overload SLO acceptance.

No production certification or authorization to handle customer financial or
other consequential actions is established by this experiment.
