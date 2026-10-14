# Current acceptance — local audit, October 13, 2026

**Engineering alpha; unrestricted consequential-action production NO-GO.**
Source baseline is integration cc705be8fff535883eee2876c88b0cca4e54da61 plus
the consolidated fixes. The initial audit was completed locally without online
writes. The owner subsequently authorized publishing the fixes for review on
October 14; see [publication status](PUBLICATION_STATUS_2026-10-14.md).
Historical documents apply to their own revisions.

## Executed local verification

| Scope | Result |
| --- | --- |
| 26 frozen remote branches, Linux 3.11 + real PostgreSQL | 24 pass, 2 fail as-is |
| 26 frozen remote branches, Windows 3.12 + real PostgreSQL | 10 pass, 16 fail as-is |
| 26 standalone branch wheels | 9 source-complete imports; 17 omit required src modules |
| Consolidated Windows candidate | 556 passed, 3 skipped, 8 subtests passed in 65.31s (0:01:05) |
| Consolidated Linux candidate | 559 passed, 8 subtests passed in 64.47s (0:01:04) |
| Security scan of frozen pre-fix candidate | 4 medium findings; 120/318 files fully reviewed, remaining artifacts searched/tested but not fully statically audited |
| AWS read-only audit | 75 verified API calls across 17 regions; no EC2/EBS or AgentBridge lab IAM/SG/parameter resources found |
| Historical AWS acceptance | SSM records retain primary/standby, stale-leader, observer, promotion and wheel rollback success markers |
| Outreach claims | Gmail confirms five interview invitations and a third evaluator invitation; no completed reviews/interviews in inspected records |

The three Windows skips are the two POSIX process-kill drills and POSIX key-mode
semantics; Linux ran them. JUnit counts include the separately reported subtests.
The branch dependency matrix uses recorded current shared dependencies, not every
historic lock or protocol version. See [full branch decisions](BRANCH_REVIEW_2026-10-13.md).

## Local implementation completed

- Preserve latest remote Evidence verifier, fail-closed proxy and task-state work;
  carry forward signed trust-policy rotation, revocation, restore floors and atomic
  evidence/budget/audit settlement from the earlier local continuation.
- Fix JWKS removed-key trust, invalid-kid refresh amplification, HTTP metric
  cardinality and known administrator defaults, with adversarial regressions.
- Correct PostgreSQL production observer row handling and test positive read-only
  principals in both production spellings; fix cross-worker identity lookup/revoke.
- Add durable owner-scoped task status, compare-and-update, cancellation status,
  cursor replay, admission/event limits and bounded pull consumption.
- Package agentbridge-verify-evidence, requiring independently retained expected
  action and trust files at the CLI; reject malformed executable wires before
  dispatch and remove the legacy translator dependency from the live proxy.
- Strengthen concurrency assertions, prepare Windows CI, source-pin Actions,
  reconcile dependency updates, fix publication recipe parity and require explicit
  owner publication configuration. No protected environment was configured online.
- Organize canonical docs, correct stale roadmap/deployment statements, add a
  complete document catalog, local-link checker and private-work/build exclusions.

## Four products and remaining work

| Offering | Local position | Remaining acceptance |
| --- | --- | --- |
| OSS | Installable engineering SDK, tested narrow adapters and durable status foundation | Full declared version/transport conformance, independent installations, real network task streaming |
| Trust | Tested signed authorization, scoped approvals, SQL budgets, duplicate protection and participating destination fencing | Non-bypassable third-party destination integration, operated workload identity and independent security acceptance |
| Evidence | Signed receipts/readback/review, current-key journal, atomic settlement/audit and offline verifier | Independent signer/observer/retention administration and authoritative external source acceptance |
| Enterprise | Deployment references, OIDC/RBAC, metrics and bounded recovery evidence | Automated split-brain-safe HA, tenant service isolation, signed public provenance, live service migration/rollback, production SLOs and support contracts |

Internal work remains in those engineering qualifications; it is not relabeled
external merely because it is difficult. External work requires independently
controlled identities/destinations/reviewers, returned developer reports, real
buyer conversations and a supervised design partner. No four-product commercial
release, settlement certification or customer traction is established.

## Scope and authorization

The updated PDF has 108 pages; its SHA256 is
ba76b9a7fdd0d100d93c1005c86846c5dba76e7dde84d6db99472ee88e08eb31.
Historical PDF instructions were treated as project context, not fresh authority
to send mail, use exposed credentials, provision cloud resources or publish code.
No secret values were retrieved through AWS, no infrastructure was provisioned,
and no email was sent. The connected AWS Free plan reports ACTIVE with USD 140
remaining credits; that is not a final cost invoice or authorization to spend.

The GitHub ruleset is active but has zero required independent approvals and
administrator bypass. Account 2FA, private reporting and scanning settings remain
unverified through the inspected repository response. License and ownership
acceptance require separate evidence; no existing license was changed.

## Installed package and deployment checks

Two wheel builds with the same SOURCE_DATE_EPOCH were byte-identical. The wheel
contains all 77 Python modules and the dashboard;
its SHA256 is `428efe2382cb853285616883ddae330946fc63731778bb6b095ba77095475b54`. A new isolated environment installed the
hash-locked core, passed pip check, and ran all 12 Trust/Evidence checks outside
the checkout. The installed offline CLI accepted the separately retained expected
action and rejected a mismatched action. After explicitly adding the MCP extra,
both installed CLI demos reached a real local stdio tool; the governed demo
verified its audit chain. The core-only CLI explains the missing optional SDK.
Live targets requiring missing SDKs are rejected at startup. These are narrow
SDK and transport checks, not complete protocol conformance.

The final release-review image is `agentbridge:local-audit-20261013`, ID
`sha256:e104e6321eeeb867b8d5b95be5c37f8f9c2e07c430824c3073b91823fd334156`. Six real HTTP/process checks passed with production-mode
PostgreSQL, a read-only application filesystem and an operator key generated only
for the disposable test. The harness verified removal of its own containers and
network. The image includes a supplementary hash-locked PostgreSQL driver graph;
the minimal core image does not promise optional transport SDKs. pip-audit found
zero known advisories in the 22-package hash-locked runtime/driver graph at scan
time. Optional development SDK dependencies are outside that result.

The version remains the existing 1.0.0 metadata; no release was published.
Hosted checks for the review branch are tracked in the publication PR. Local tests do not substitute
for protected exact-head CI, independent review or production acceptance.

## Final recovery and image scan

Final local Trivy 0.69.1 scanning, using a freshly downloaded vulnerability
database, reported zero HIGH/CRITICAL vulnerabilities in the Alpine 3.22.4 OS
and Python packages of the reviewed image. Lower severities and optional SDK
images were outside that severity-filtered result. This is not a guarantee
against unknown vulnerabilities or a production security certificate.

The final PostgreSQL logical-restore drill passed five checks: externally pinned
signing revisions rejected the older restored keys, automatic replay was denied,
the unknown operation and reservation survived, and the restored audit chain
remained valid. Both temporary databases and the drill container were removed.

The final candidate was copied into D:/codex/agentbridge after preserving the
21 original dirty paths, the original index patch, a backup branch at the prior
HEAD, and a verified Git bundle containing all 26 remote heads. Only the local
branch/index was aligned to integration cc705be8; no commit was created.
The frozen pre-fix security worktree remains unchanged for reproducible evidence.
The live branch set was re-fetched and matched all 26 audited SHAs after the
usage-limit interruption. Final handoff is October 14, 2026, Asia/Karachi.
