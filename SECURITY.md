# AgentBridge Security Policy

> **Production target restriction:** HTTP named-target execution is disabled for
> generic MCP/A2A/ACP transports in `prod` and `production` until destination-atomic
> authority/fencing is qualified. Translation and nonproduction synthetic evaluation
> remain available. See [destination contract](docs/PRODUCTION_TARGET_QUALIFICATION_2026-10-14.md).

**Status: experimental engineering alpha.** No released build is certified for consequential customer actions, financial transactions, or regulated operations. Do not rely on internal CI as an independent audit.

## Supported scope and versions

The recorded `main` baseline is `73aafd60a0eec121a10245a307a4a8ee268f7ed5`. The cumulative tenant draft source is `46777f8c953690fca81c6d11e7b70372b8dd5c77` (PRs #56–#69); its recorded CI is distinct from main and from the older unsigned evaluator wheel. See [current source and remaining gates](docs/CURRENT_ALPHA_STATUS.md). Historical branch reports describe their own revisions. No version has completed the production acceptance process. The `pyproject.toml` package version alone is not proof of a published, supported, signed release. Quote the exact Git commit SHA, Python version and supported protocol subset in reports.

## Reporting vulnerabilities privately

Do **not** open a public issue, pull request, discussion or comment containing an exploitable vulnerability, credentials, private keys or customer data.

Use GitHub's **Report a vulnerability** option under this repository's Security tab **if private vulnerability reporting is enabled**. If it is not enabled, contact the repository owner via a verified private channel from their GitHub profile to arrange confidential disclosure. Do not send sensitive details to an unverified address.

Provide an affected commit, minimal non-sensitive reproduction, impact and expected behavior. Maintainers will triage as resources allow; no guaranteed 48-hour response or remediation service level is currently offered. Do not perform destructive testing on third-party systems without written permission.

## Threat boundaries

- Authorization, approvals and budget policy apply only to supported and enforced dispatch paths. Uninstrumented SDK calls and third-party targets are not automatically protected.
- Destination fencing must be enforced **at the real action destination**. The PostgreSQL/SQLite reference implementations do not establish universal exactly-once effects.
- Ed25519 signatures authenticate the signer's claims. They do not alone prove physical fulfillment, financial settlement, or independent custody.
- Real-world verification requires independent access to authoritative target state and appropriately controlled keys. The AWS two-host test exercised separate-host signing but not separate organizational administration.
- Production CNI and workload-authenticated egress, arbitrary third-party destination enforcement, split-brain-safe automated HA, and independent release provenance remain unqualified.
- TLS must be enforced at an appropriate transport boundary. Enforce trusted-origin outbound traffic, hostname verification and explicit deny policies.
- Do not commit API keys, database URLs containing credentials, private signing keys, exported secrets, production data or unredacted failure logs.

## Operator safeguards

Use least-privilege per-service principals, separate write and observer rights, secure key rotation/revocation, durable audit retention and off-system backup. Fail closed on unresolved external outcomes. Isolate synthetic testing from actual payment, employment, medical and other consequential workflows.

For current engineering acceptance limitations start with [current alpha status](docs/CURRENT_ALPHA_STATUS.md). Historical evidence includes [integration security review](docs/INTEGRATION_SECURITY_REVIEW_2026.md), [AWS two-host evidence](docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md), and [code/IP protection policy](docs/CODE_PROTECTION_AND_IP_POLICY_2026.md).

This policy does not promise security certification, regulatory compliance or a fixed incident response SLA.
