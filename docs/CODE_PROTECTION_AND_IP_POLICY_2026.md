# AgentBridge code protection and intellectual-property controls

**Status:** engineering governance proposal; not legal advice or a completed account-security audit.

## Rights already granted
The public repository contains Apache License 2.0 code. Prior recipients retain rights associated with their received licensed copies. Removing or modifying a LICENSE file does not retroactively revoke grants. Restrictive relicensing is **not authorized** here. Before distributing new proprietary modules, inventory contributions, dependencies, applicable copyrights, employment/contractor assignments and any AI-assisted development terms; obtain qualified IP counsel review. A NOTICE identifies attribution, but does not alone establish title to every contribution.

## Enforce in repository settings (owner action required)
1. Enable 2FA/passkey for all privileged maintainers; use a hardware security key for the owner and recovery codes stored offline. Review personal access tokens, installed apps, deploy keys and collaborator access quarterly; remove unused write privileges.
2. Create a ruleset for `main` and release branches that disallows force-push and deletion; requires pull requests, code-owner review, latest-head status checks and resolved conversations. Scope administrator bypass tightly and audit every exception. **A CODEOWNERS file alone does not enforce reviews.**
3. Enable Dependabot security updates, dependency review, secret scanning/push protection (where available), private vulnerability reporting and CodeQL or equivalent SAST; verify repository entitlement and actual settings in GitHub UI.
4. Restrict GitHub Actions token permissions to minimum required, pin third-party actions by trusted commit SHA as a separate audited change, protect publishing environments with manual reviewers and prevent untrusted fork PRs from receiving signing or cloud credentials.
5. Back up Git history, issue/PR records, release metadata and key release artifacts off GitHub with encrypted, access-controlled storage; periodically rehearse recovery. Never publish signing keys or customer records.

## Commercial boundaries
Keep the existing OSS kernel and protocols under their published license. Design **new, separable** enterprise capabilities—managed tenancy operations, retention workflows, operator custody integration, priority support, deployments and contractual service—behind separately owned modules and written agreements only after IP and license review. Do not claim exclusivity over source already licensed under Apache 2.0, nor copy third-party code without attribution and compatible grants.

## Trade-secret handling
Store confidential commercial source in a separately access-controlled private repository only when the code's provenance permits. Use least-privilege CI, mandatory review, no secrets in code, and tested disaster recovery. Publication destroys secrecy of the published material; treat private implementation details, credentials, customer data and unreleased designs as separate information classes.

## Incident protocol
Suspected token or key leak: revoke/rotate in the actual provider, examine audit logs and exposure window, invalidate impacted evidence signatures as appropriate, and document notification decisions. Removing a committed secret without rotation is insufficient. Avoid copying suspected credentials into public issue comments.

## Verification status — October 13 local audit

Read-only GitHub verification confirms active ruleset `25007045` for main,
release/* and integration/*: PRs, both Python checks, resolved threads, blocked
force pushes and deletion. Required approving review count is zero; code-owner
review is not enforced; repository administrators retain always-on bypass.
CODEOWNERS is present. Secret scanning, push protection, private reporting,
account 2FA and protected publisher settings were not independently available
through the inspected connector response. No settings were changed in this audit.
