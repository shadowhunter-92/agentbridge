# External security review and pilot program

Status: OPEN — no external review, pilot, certification or endorsement is claimed.

## Scope for independent review

Repository: https://github.com/shadowhunter-92/agentbridge
Release review branch: release/rc0-hardening-and-validation-2026-10

Ask experienced engineers to examine: identity spoofing, request-bound signatures, direct-SDK nonce replay, SSRF/egress and command execution, approval concurrency, multiworker budget atomicity, uncertain remote side effects, tamper evidence, and PostgreSQL failover. Do not represent a reviewer accepting an invitation as certification.

## Pilot acceptance

Limit first installations to **read-only or synthetic, isolated targets**. Provide reproducible examples, tests and a sample approved workflow. No customer credentials, financial transfers, unrestricted shell commands or autonomous production mutations. Invite 3 unrelated developers to integrate within 30 minutes, record installation difficulty, unsolved problems, unexpected dependencies and whether they would keep it installed. Ask each for permission before publishing feedback.

## 15-minute reviewer invitation template

Subject: Independent technical review request — AgentBridge (open-source agent authorization prototype)

Hello,

I'm seeking candid security and developer feedback on AgentBridge, an experimental Python project for cross-protocol agent actions, authorization and audit evidence. It is **not production-certified**. Would you consider reviewing its supported scope, especially privilege boundaries, authorization races, remote execution ambiguity, audit integrity and safe integration with MCP/A2A?

Repository: https://github.com/shadowhunter-92/agentbridge
Review branch: release/rc0-hardening-and-validation-2026-10

A written critique, reproducible failing test or a short conversation would be valuable. We will not treat your review as an endorsement, and we will credit you only with permission. Please avoid submitting sensitive vulnerabilities publicly; we can coordinate a private disclosure route.

Thank you.

## Evidence required

For each reviewer/pilot, record explicit invitation, consent, scope, source version, test environment, observations, severity, reproducible issue links, remediation, retest, independent sign-off, and permission to quote. Do not fabricate reviewer names, adoption numbers or feedback.

## Candidate public channels to verify before contact

- OWASP GenAI Security Project official community channels and contribution pathways
- OpenSSF public open-source security review processes, if the project meets their criteria
- MCP project official discussions and maintainers, where project promotion is permitted
- agentgateway and ContextForge upstream issue discussions (only narrowly scoped technical compatibility questions, no unsolicited promotional issues)

Funding/partner applications and direct outreach require actual eligibility, verified contact endpoints, and respectful one-to-one messages. Do not spam issue trackers or suggest a security assessment has been completed.

## Release-blocking test program

See docs/PRODUCTION_OPERATOR_DRILLS.md. Assign independent operators for process-kill, network partition, PostgreSQL failover/restore, real target idempotency and audit rollback drills. Preserve logs and outputs. The release decision remains NO-GO until the defined controls are demonstrably satisfied.
