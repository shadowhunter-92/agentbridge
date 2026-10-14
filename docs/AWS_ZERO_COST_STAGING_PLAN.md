# AgentBridge AWS staging — strict $0 preparation

**Budget authorization: $0. This is configuration-only, NOT an AWS deployment.**
No paid AWS resources may be created or modified without separate explicit approval. AWS Budgets alerts are not hard spending limits. A new EKS control plane, load balancer, NAT gateway, RDS instance, persistent storage, IP address or other resources can incur costs even when idle.

## What is currently available

- Green 13-job integration CI and passing disposable two-node kind+Calico CNI policy enforcement (see PR #41 and GitHub Actions).
- The AWS CloudFormation file `infra/aws/staging-audit-only.template.json` defines exactly **one read-only IAM audit role** and requires an **existing, administrator-approved** GitHub OIDC provider. The template is **not applied**.
- `tools/validate_aws_zero_cost.py` and `.github/workflows/aws-zero-cost-preflight.yml` provide purely offline preflight validation. Their CI has no AWS role, no OIDC token and no `aws` deployment commands.
- No known AWS account ID, region, existing IAM OIDC provider, GitHub AWS variable, cost center or account administrator consent has been supplied. Do not guess them or ask for access keys in chat.

## Safe optional setup by the AWS account owner

1. Identify whether a genuinely existing AWS account and AWS-operated cluster are available without incremental billing. **Do not create anything yet**; discovery itself can have service-specific charges. Require owner confirmation of the account's cost policy.
2. The owner independently inspects the one-role CloudFormation template, the exact repo/branch claim restriction, permissions and their organization's GitHub OIDC trust policy. Its creation is a mutation of IAM and must be explicitly approved.
3. If approved and independently applied by the owner, store the resulting role ARN as a repository variable `AWS_STAGING_AUDIT_ROLE_ARN`. Never supply a static AWS access key or private signer. No workflow in this change assumes the role or calls AWS.
4. Require a GitHub environment with manual reviewers, restricted branch policy and explicit non-zero deployment approval before adding any deploy workflow. Separate **read-only discovery role** from **temporary staging provisioner**; never expand the audit role to wildcard deployment.
5. Before first paid deployment, provide a line-item forecast for EKS, workers, RDS, load balancing, NAT/data transfer, logs, registry and retained artifacts. Confirm a hard user-approved cap and teardown owner. If expected incremental cost exceeds $0, do not deploy.

## Execution while budget remains $0

Use existing hosted CI for disposable kind/Calico, PostgreSQL failover/PITR, SDK provenance tests, offline lint, synthetic upgrade/rollback and protocol compatibility. Retain log/artifact SHA, time, environment and pass/fail details. These are real hosted-runner tests, but not an independently operated AWS staging service.

## P0–P2 status carried forward

- **P0:** Independent observer custody, real third-party destination fencing, AWS network/workload identity and TLS egress still OPEN.
- **P1:** Automated split-brain-safe HA, operated RPO/RTO, independently signed published artifacts, application rollback still OPEN.
- **P2:** Full advertised MCP/A2A reference transport/lifecycle coverage and production-shaped service SLOs OPEN.

**Stop signal:** Any AWS resource creation, API mutation, or chargeable operation without separate owner approval. This document and static preflight do not authorize such actions.
