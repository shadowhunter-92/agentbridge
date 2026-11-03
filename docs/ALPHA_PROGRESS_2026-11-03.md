# Engineering alpha progress and acceptance — November 3, 2026

**Overall: PARTIALLY TESTED. Unrestricted consequential-action production: BLOCKED / NO-GO.**

This checkpoint records evidence through maintained main `44a06c364e348966e0b14c724f14e3a14d192433`, tree `b9fe952af2e9b92bb98c275315a426213d7c5eb5`. The document itself is a later documentation-only follow-up and is not covered by that main run. Earlier dated records retain their original cutoffs.

## Verified bounded unit

The owner approved normal merging PR #85 at source `c4fe9a4f9fa1fd58589bd2f3a9c27e734fe29e7f`. Main's ordered parents are `3b8a246101e72667e09bf0416a6b8cd307099bd1` and that source commit. Internal review matched all 464 published blobs/modes to the sealed tree. All 103 product runtime files, Apache-2.0 licensing, CODEOWNERS, original default drill and Windows 30-minute budget were preserved. All 16 remote branch names were retained; non-main SHAs were unchanged at merge verification.

| Evidence | Exact scope and result |
| --- | --- |
| Local maintained-main composition | 193 distinct passes: 123 offline harness plus 70 fencing/deadline/destination regressions; zero failures/errors/skips; source stable during execution. Only the dated results document changed afterward. |
| Source PR CI | All 24 checks across seven workflows passed on attempt 1 at exact `c4fe9a4`. [Core run 41455144424](https://github.com/shadowhunter-92/agentbridge/actions/runs/41455144424). |
| Own merged-main core CI | All 16 jobs passed on attempt 1 at exact `44a06c3`. [Run 41580327205](https://github.com/shadowhunter-92/agentbridge/actions/runs/41580327205). |
| Main Windows job | 1,805 passes, 971 expected skips, three warnings and eight subtests; pytest 333.58s, whole job 418s; Trust/Evidence example and documentation follow-ups passed. |
| Main PostgreSQL job | 1,962 passes, 145 expected skips and six warnings; pytest 454.01s; recovery/load/smoke follow-ups passed. |
| Main drill artifact | Artifact 13205471234 binds the exact run/main SHA and retains both original and worker-lifecycle JSON reports. Both scenarios passed. |

These cohorts overlap and are not added into a unique repository-wide total. PR and main timings belong to separate runs; neither is a production SLO.

The new explicit disposable scenario renews an old worker twice, drains renewal, observes database-clock expiry and acquires a higher epoch through one replacement. That participant attempts one effect with an injected lost acknowledgment; another connection reads the exact signed result. Stale renewal/effect probes refuse, and the owned children exit normally. The original default scenario remains. See the [controlled-trial record](HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md).

**VERIFIED IN CI** applies to that bounded component and its negative tests. It is not consensus, physical database promotion, actual network partition recovery, full governed admission/accounting reconciliation, independent custody or universal exactly-once execution. A signed receipt authenticates the signer's statement; it is not independent proof of physical or financial completion. No uncertain effect is automatically replayed.

## Handoff progress checklist

| Handoff area | Status | Evidence boundary / remaining action |
| --- | --- | --- |
| Phase 1 checkpoint registry | VERIFIED IN CI | Incorporated historical checkpoint corrections remain in maintained history. Bounded records/JSON do not bound all physical pages, indexed retention or separate journals. |
| Phase 2 external destination enforcement | PARTIALLY TESTED | Contract/sandbox observations do not prove external destination-atomic monotonic fencing. Qualify an actual enforcing target and separate authoritative observer; keep unsupported consequential modes closed. |
| Phase 3 network and workload identity | PARTIALLY TESTED | Earlier reference/control tests remain separate. The November 2 AWS guard, policy probe and isolated control plane ran, but no EC2 host or cluster traffic was launched. Actual multi-node CNI, workload mTLS, IPv6 and bypass traffic remain open. Reference relays remain sandbox-only. |
| Phase 4 HA and recovery | PARTIALLY TESTED | Worker-lifecycle component VERIFIED IN CI and prior local component trials retained. Forced process failure, real acquire/renew response loss, partition/rejoin, physical fencing/election, governed uncertainty, active migration/rollback and repeated RPO/RTO remain open. |
| Phase 5 release provenance | PARTIALLY TESTED | Existing signing controls are not trusted published release qualification. Verify actual installed published artifacts, transitive dependency/SBOM integrity, identity, rotation/revocation and upgrade/rollback. No SLSA-level or institutional-signing claim is added. |
| Phase 6 protocol fidelity | PARTIALLY TESTED | Supported subset and pinned official-version/transport evidence govern claims. New-task, cancellation, notification/OAuth, reconnect and cross-version gaps require exact conformance results; unsupported semantics must refuse. |
| Phase 7 performance and operations | PARTIALLY TESTED | Existing smoke/load/component results are not sustained full-route SLO evidence. Measure identity→policy→approval→ledger→destination→readback→evidence→audit, fairness/backpressure, RSS/CPU and latency under sustained concurrency. |
| Phase 8 external validation | BLOCKED | Prepared packages and sent inquiries are not acceptance. Still requires three unrelated developer evaluations, five buyer interviews, independent security review, separately administered destination/readback and a written supervised pilot. Legal sufficiency requires qualified review. |
| Phase 9 current documentation | PARTIALLY TESTED | This narrow entry-point reconciliation records exact current evidence. The larger historical document/branch register and other unexamined claims still require their own dispositions. |
| Isolated replay-capacity candidate P35 | BLOCKED | Required separate review remains pending; this work does not modify or integrate it. |

## Expired cloud trial and permissions

The November 2 owner-approved $5 planning trial expired during a usage-limit interruption. No launch inputs, ClientTokens or RunInstances request were produced in this workflow. No actual host, CNI, PKI, traffic or physical HA result exists from it.

On November 3, exact-owned teardown succeeded after fresh identity, tags, RoleIds/ProfileId, code and dependency checks: timer/target/function, two roles/profile/policies, reciprocal security groups, subnet/routes/gateway and VPC were removed. Independent follow-up performed 102 successful read APIs across 17 regions; 97 owned-resource list checks were empty and the shared default VPC/DHCP were preserved. An initial connector 100-call cap left one read unexecuted; a separate request completed it. This is current absence evidence, not a CloudTrail reconstruction or final billing statement.

The renewed trial has no remaining execution authority. Future paid infrastructure/access needs its applicable owner decision and a fresh window. Main merges, deletion, release/publication and outside correspondence retain their separate approval conditions. Existing outreach promises and opt-outs remain in force; no additional message is sent by this unit.

## Priority and responsibility register

1. Maintainer/engineering: finish the actual network execution path with enough execution headroom before a new timed trial; never substitute YAML, readiness or a successful guard probe for attempted traffic.
2. Engineering: complete forced-worker and real response-loss cases, then physical/partition/migration tests and full governed reconciliation. Preserve UNKNOWN until authoritative evidence resolves it.
3. Engineering: qualify remaining retention/evidence-storage boundaries, supported protocol semantics, trusted artifact installation and sustained full-route performance. Reuse existing implementations and document unsupported cases.
4. Maintainer: review narrowly scoped publications and exact-head CI; authorize each applicable protected-main merge or new cloud window. No branch deletion is proposed here.
5. External participants/operators: supply independent review, developer/buyer feedback, separated custody and supervised pilot evidence. Internal tests and email delivery cannot substitute for these gates.

Apache-2.0 and CODEOWNERS remain unchanged. Engineering alpha remains the accepted scope; no production, legal, commercial or external-certification acceptance is asserted.
