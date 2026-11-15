# Independent audit and reconciliation — November13,2026

**PARTIALLY TESTED; unrestricted consequential-action production BLOCKED / NO-GO.**

Audited baseline and unchanged ending source: `f309a35cb5c3ec4164acea5ba2622dc04be6807c`, tree `17fd9e48708ebed43971a4d0b53b9e6cf703c609`. This document is a later local audit addition; the baseline CI does not cover this addition. Metadata window: November13 approximately05:22–10:40UTC. Branch/PR counts are timestamped observations and drift.

The supplied snapshot is evidence to verify, not authority over observed source. Its stale merge/count/CI claims are refuted below. No remediation occurred before this audit was written. No new merge, publication, deletion, protection change, cloud work, release, external message or P35 work is authorized by this report. Five earlier explicitly approved merges are already recorded facts.

Phase0 metadata and literal-pin inventory is recorded. Full historical receipt rehash/semantic acceptance remains **PARTIALLY TESTED**, with precise limits below; this report does not claim every engineering requirement is qualified.

## Claim reconciliation

| Claim | Source | Verified? | Actual observed value | Evidence (SHA / run ID / file:line) |
| --- | --- | --- | --- | --- |
| Current main is 35f3722 | Supplied November13 snapshot | FALSE / STALE | f309a35cb5c3ec4164acea5ba2622dc04be6807c; tree 17fd9e48708ebed43971a4d0b53b9e6cf703c609 | Owner-approved PR87-91 merge readbacks; main run43371818001 |
| 21 branches | Supplied snapshot | TRUE | 21; no branch deleted; observed November13 10:27:40Z | All-paged branch API; matrix below |
| 11 open /75 closed PRs | Supplied snapshot | FALSE / STALE | 6 open /81 closed;87 total | All-paged pulls collection |
| PR87-91 are open/in flight | Supplied snapshot | FALSE / STALE | All five normally merged after explicit owner approval; heads preserved | Merge table below |
| PR90/91 have2 unresolved jobs | Supplied snapshot | FALSE / STALE | Each reached24/24 before merge; no unresolved job at approved heads | Runs43368983122 /43369287096 plus specialized workflow evidence |
| PR91 modifies production behavior | Supplied snapshot merge classification | FALSE | Tools/tests/workflow/docs unit; no src runtime edits | PR91 changed-file inventory |
| PR87/88 preserve runtime/license/CODEOWNERS | Supplied snapshot | TRUE | Examples/tests/docs only; no src, LICENSE, NOTICE or CODEOWNERS changes | Exact reviewed diffs daf350b /6cbc8da |
| Open dependency PRs are79-84 | Supplied snapshot | FALSE / STALE | 79,81,82,83,84,92;80closed and replaced | Current exact PR table below |
| PR84 is23/24 | Supplied snapshot | FALSE | 22success; package-review failed; container-security-review skipped | Run41332417404; jobs124925113473 /124925599043 |
| PR84 is open12days | Supplied snapshot | TRUE, DATE-SCOPED | Created November1; approximately12days as of November13 | PR84 created_at; not a timeless count |
| All dependency branches are4behind, actions2behind | Supplied snapshot | FALSE / STALE | Five pip heads1ahead/14behind;92oneahead/0behind | Immutable compare against f309a35 |
| Dependabot label dependencies is absent | Supplied snapshot | TRUE, INCOMPLETE | Both dependencies and ci absent;9defaultlabels only | Direct label API inventory SHA256761f1fa5c17df13fc2177383879a2691d9dc352097a94e16dac4518452bab14f |
| Pydantic advisories exist and2.14.2 fixes them | Supplied snapshot | TRUE UPSTREAM; APPLICABILITY OPEN | Locked2.14.1 in affected ranges; inspected first-party schemas avoid affected patterns; optional nested SDK schemas unexamined | Upstream Pydantic advisory pages; dependency audit |
| PR84 CI demonstrates runtime incompatibility | Potential interpretation | FALSE | Observed failure is intentional manifest/hash-lock comparison; core2.50.1 vs required2.50.2 | Failed compile/diff step; original log SHA256454cd59c7e2b706712c3cf47ad5f05f9bed06a8636a6bbb90ca3084f3b0c45f1 |
| November3 ALPHA_PROGRESS old pins/counts are wrong | Supplied snapshot | FALSE AS STATED | Document explicitly says checkpoint through44a06c3;16branches was a historical readback | ALPHA_PROGRESS_2026-11-03.md:5-9; preserve history |
| CURRENT_ALPHA_STATUS is current at44a06c3 | Current navigation | FALSE / STALE | Current entry points need November13 checkpoint and superseding links | CURRENT_ALPHA_STATUS.md:4,10-12,264 |
| Docs index is complete | docs/README.md:32 | FALSE | 94distinctMarkdown targets;10tracked docs omitted; current label saysOctober22 | Documentation audit and omitted list below |
| Root README surfaces current governed demo | Storefront requirement | FALSE | Quickstart pinsb0afb7f; new governed_mcp_demo absent | README.md:81-91 |
| Existing docs have missing local inline targets | Potential interpretation | FALSE FOR CHECKED GRAMMAR | Checker passes;330local inline targets;0missing; no reference-style or local fragment links found | Exact f309 checker exit0; external availability excluded |
| Contained branches need another merge | Potential interpretation | FALSE | 10recent and4legacy heads have0ahead; preserve histories/owner gates | Branch matrix and merge-base checks |
| prod/readiness-pass is unprotected vs3siblings | Supplied snapshot | TRUE | Four protected flags:main plus3maintainedlegacy refs | All-paged branch collection; detailed rules not administration-audited |
| Ancestry alone closes Issue38/authorizes deletion | Potential interpretation | FALSE | All5commits retained; behavioral cross-check and owner acceptance still needed | LEGACY_BRANCH_RECONCILIATION_2026.md:18-46; no deletion approval |
| No actual cluster traffic ever launched | Supplied snapshot | NOT ESTABLISHED / OVERBROAD | Issue40 historical comment6140005048 reports two-node kind/Calico attempted traffic; later AWS trial remains unqualified | Issue40 full comments; historical CNI run38358713825 |
| Current issue threads contain returned external acceptance | External gate | FALSE FOR INSPECTED THREADS | 5issues/21comments, allowner-authored; no returned independent evaluation/security/interview/pilot artifacts | Issue33/36/38/40/44 full paginated histories |
| Entire internal kernel is complete | Supplied one-line summary | NOT ESTABLISHED | Bounded units verified; full protocol/recovery/storage/release/performance gates still open | Acceptance register below; file/class existence is insufficient |
| MCP container negative scenarios/hash closure and mock aggregate storage are done | In-flight gap list | FALSE | Known internal gaps; native/container success is not all-negative acceptance | GOVERNED_MCP_DEMO_2026-11-12.md; OFFLINE_STRIPE_STYLE_CONTRACT_2026-11-12.md |
| Current external_validator/design_partner kits exist | Requested Phase5 | FALSE | No tracked evaluation/ tree; older docs material and unmerged local preparation exist | Tracked486file inventory; no assertion about private local drafts |
| Every listed historical Git pin exists | Literal audit | TRUE | 166uniqueGitpins:160commits/6trees; all resolve;160commits ancestors of f309 | Pin appendices; existence does not verify behavior |
| Every referenced workflow run passed | Potential interpretation | FALSE; HISTORY ACCURATE | 27distinct docruns:26success,1failure40046824359 at7a10a5f, already explicitly retained | Run appendix; do not erase original failure |

## Approved merges and independently successful current main

| PR | Exact reviewed head | Merge commit |
| --- | --- | --- |
| 87 | daf350b26fd900c856f1cad2088544a1ff48642f | 54f213376586d9b6ac60434ce67dcf8cad5cf373 |
| 88 | 6cbc8da9407c6d977bab2da8b85fe30a351c61ca | 9194761bdc34b878a1d4a3e0164e04b53da43b0d |
| 89 | aad1153a89bcecf018859720b3dff0a18afc2d8a | 722dd0668b008af52822d3e01169b7c0db6ee5ab |
| 90 | f0de581e9adad40cff16408cc09acf0995173b60 | 6a2a06a2f52f96fa066bda96e16062c39b06eb17 |
| 91 | 6aea3260cda650e76d080705e171d6e480a07c97 | f309a35cb5c3ec4164acea5ba2622dc04be6807c |

Each source passed24/24 across7workflows before owner-approved normal merge. Joint local composition2313030879574fa66400e411f7b8f880eaa0989e passed486cases with52explicit PostgreSQL skips; its tree exactly equals current main. Cohorts overlap and are not summed into a repository-wide total.

Current main own [CI43371818001](https://github.com/shadowhunter-92/agentbridge/actions/runs/43371818001) passed **16/16jobs** on attempt1, separately from the24PR checks. These are CI component observations, not production/network/HA/custody acceptance.

| Main job | Job ID | Result |
| --- | --- | --- |
| postgres-stale-leader-drill | 131709072649 | success |
| sustained-sql-soak | 131709072819 | success |
| postgres-tcp-partition-drill | 131709072860 | success |
| package-review | 131709072897 | success |
| evaluator-clean-wheel (3.11) | 131709072927 | success |
| test (3.11) | 131709072935 | success |
| postgres-replica-drill | 131709072949 | success |
| evaluator-clean-wheel (3.12) | 131709072971 | success |
| network-protocol-conformance (windows-latest) | 131709072974 | success |
| egress-isolation-drill | 131709072988 | success |
| test (3.12) | 131709072992 | success |
| postgres-integration | 131709073014 | success |
| network-protocol-conformance (ubuntu-latest) | 131709073019 | success |
| postgres-pitr-drill | 131709073080 | success |
| windows-test | 131709073084 | success |
| container-security-review | 131711222882 | success |

## Every open PR

| PR | Head | Base recorded by old PR | Ahead / behind f309 | Success / total | Nonpassing jobs | Core CI |
| --- | --- | --- | --- | --- | --- | --- |
| 79 | bf0a5e435189f0ac3aa7df58791edf38682f9d43 | 3b8a246101e72667e09bf0416a6b8cd307099bd1 | 1/14 | 24/24 | None | 41332383684 |
| 81 | 3cbb08555af5189071080ed2708dde3bccc52a28 | 3b8a246101e72667e09bf0416a6b8cd307099bd1 | 1/14 | 24/24 | None | 41332389113 |
| 82 | 00a038cc01114d41ed2b48b4fbb9ee50b7bebee8 | 3b8a246101e72667e09bf0416a6b8cd307099bd1 | 1/14 | 24/24 | None | 41332399473 |
| 83 | ba1df2ab6d492975a39f333c29bdd859e2136516 | 3b8a246101e72667e09bf0416a6b8cd307099bd1 | 1/14 | 24/24 | None | 41332405287 |
| 84 | 23e9851bc5e987eed7e2d50fbdf2491343ad75f8 | 3b8a246101e72667e09bf0416a6b8cd307099bd1 | 1/14 | 22/24 | package-review (failure); container-security-review (skipped) | 41332417404 |
| 92 | 04a497ad84caeac1c80ff3d88892a1ac89a8f307 | f309a35cb5c3ec4164acea5ba2622dc04be6807c | 1/0 | 24/24 | None | 43371968174 |

Five pip runs are historical November1/old-base evidence, not current-main integration qualification. Every24job name/ID and all7runIDs for each openPR are retained in `AgentBridge-dependency-audit-2026-11-13.json`. #92 includes upload-artifact major v4→v7; upstream SHA resolution plus passing CI is not a complete action-vendor security or publishing-path qualification. No release workflow was dispatched.

#84 smallest correction is coherent manifests/Pydantic+core hash lock; preserve compile/diff guard. Static advisory triage stays needs_review until nested optional SDK schemas/deployments are examined. No AgentBridge exploit is asserted.

## All21branch dispositions

| Branch | Tip SHA | Ahead / behind f309 | Protected flag | Disposition | PRs |
| --- | --- | --- | --- | --- | --- |
| dependabot/github_actions/github-actions-1e0b46b85b | 04a497ad84caeac1c80ff3d88892a1ac89a8f307 | 1/0 | False | active | #92 |
| dependabot/pip/opentelemetry-instrumentation-fastapi-gte-0.66b1 | 3cbb08555af5189071080ed2708dde3bccc52a28 | 1/14 | False | dependabot-stale | #81 |
| dependabot/pip/prometheus-client-gte-0.26.0 | ba1df2ab6d492975a39f333c29bdd859e2136516 | 1/14 | False | dependabot-stale | #83 |
| dependabot/pip/pydantic-gte-2.14.2 | 23e9851bc5e987eed7e2d50fbdf2491343ad75f8 | 1/14 | False | dependabot-stale | #84 |
| dependabot/pip/pytest-asyncio-gte-1.4.1 | bf0a5e435189f0ac3aa7df58791edf38682f9d43 | 1/14 | False | dependabot-stale | #79 |
| dependabot/pip/uvicorn-gte-0.54.0 | 00a038cc01114d41ed2b48b4fbb9ee50b7bebee8 | 1/14 | False | dependabot-stale | #82 |
| docs/phase1-checkpoint-registry-2026-10-24 | 9aaf6a1a0a460d3824ad2966a57f8c5f575bdfae | 0/36 | False | contained-in-main | #74 |
| feat/durable-tenant-task-intents-2026-10-17 | 6078460affcdfb1fb878324d10d4595d5d46e0ac | 0/24 | False | contained-in-main | #73,#72,#71,#70 |
| feat/ha-bounded-deadlines-2026-10-27 | 94624d23733bdcb9ba502d87c6f3ba62cadbc4d0 | 0/11 | False | contained-in-main | #86,#85,#78,#77 |
| feat/phase2-external-destination-contracts-2026-10-25 | e06e313955bf7f34615036824520cffb75a015b6 | 0/33 | False | contained-in-main | #75 |
| feat/reconciliation-evidence-capacity-2026-10-26 | a318f42c18f326f707ee1c22d914c6a530d4f678 | 0/20 | False | contained-in-main | #76 |
| fix/ha-forced-stop-2026-11-04 | 6aea3260cda650e76d080705e171d6e480a07c97 | 0/9 | False | contained-in-main | #91 |
| fix/mcp-task-refusal-2026-11-04 | aad1153a89bcecf018859720b3dff0a18afc2d8a | 0/9 | False | contained-in-main | #89 |
| fix/retention-authority-2026-11-04 | f0de581e9adad40cff16408cc09acf0995173b60 | 0/9 | False | contained-in-main | #90 |
| integration/r4-main-reconciliation-2026-10 | 06538c52d7b6f797a0dccbaef0c519da5d819618 | 0/77 | True | legacy-preserved | #41 |
| main | f309a35cb5c3ec4164acea5ba2622dc04be6807c | 0/0 | True | active |  |
| prep/governed-mcp-demo-2026-11-12 | 6cbc8da9407c6d977bab2da8b85fe30a351c61ca | 0/9 | False | contained-in-main | #88 |
| prep/stripe-style-mock-2026-11-12 | daf350b26fd900c856f1cad2088544a1ff48642f | 0/9 | False | contained-in-main | #87 |
| prod/readiness-pass | 779e81ed6571384783310cb9e5d9bb7b71412639 | 0/570 | False | legacy-preserved | #17 |
| release/r4-internal-gates-2026-10 | f1c75d0687aa8d1e690539ec858aef171d26df01 | 0/234 | True | legacy-preserved | #34 |
| release/rc0-hardening-and-validation-2026-10 | da4e6b4280602e2d20d3b7f092c8dbae908f132e | 0/465 | True | legacy-preserved | #32 |

All21heads received a disposition. Local restored backup preserves the six earlier cleanup candidates; they remain undeleted. The owner explicitly retained the five new merged branches. No new cleanup approval was supplied. Cited commits remain reachable from protected main. Detailed branch-enforcement rules were not independently administration-audited.

## Every open issue and legacy behavior

| Issue | Title | State | Comments | Non-owner / non-bot |
| --- | --- | --- | --- | --- |
| 44 | Recruit 5 qualified Trust/Evidence buyer interviews (synthetic only) | open | 1 | 0 |
| 40 | Internal production backlog: trust, CNI, HA, release provenance and interoperability | open | 11 | 0 |
| 38 | Audit 5 unique prod/readiness-pass commits before branch archival | open | 3 | 0 |
| 36 | Seeking 3 independent AgentBridge OSS Trust/Evidence alpha evaluators | open | 6 | 0 |
| 33 | Call for independent security review and supervised read-only developer pilots | open | 0 | 0 |

#33/#36 reference older maintained release kits; #44 still calls merged#42/#43draft; #40body calls closed#34draft. Dated historical comments stay dated. None links the new#88demo. Prepare current source-bound issue updates; do not treat owner invitations/quotes as independent acceptance. Public issue threads do not exhaust private correspondence.

All five prod/readiness commits are ancestors of f309:1efbac5a8f2fe57790c0f88ac898435e8c7eec16,d4a2a4bb5517f5990786014f5f99382bb3485ae4,4db3cc1871c0e04d58221b4a3a5f25ca7b9b3eab,9006a0b2d9f30112e36470f3b834c86cfd86d9d5,779e81ed6571384783310cb9e5d9bb7b71412639. Current tests retain8SQLiteauditwriters, shared overall deadline and checked worker exceptions. Selective architectural supersession is documented; do not restore weaker4writercoverage or revive historical production/compliance claims. Independent behavioral mapping/owner acceptance remains open. This ancestry alone does not close#38.

## Documentation discrepancies and valid history

| ID | Evidence | Correction to prepare |
| --- | --- | --- |
| D01 | docs/CURRENT_ALPHA_STATUS.md:4 — The maintained snapshot is 44a06c364e348966e0b14c724f14e3a14d192433; lines10-12 direct current gates to November3 and say new main CI passed. | Add a November13 current source/tree/PR87-91 checkpoint and exact current main CI state; retain the November3 checkpoint and its source-specific CI as historical evidence. Do not transfer its16-job success to f309a35. |
| D02 | README.md:81 — Default quickstart checks out b0afb7f1da1634330747389e19c896fd7002bd83 and runs quickstart.py/demo_story.py at lines89-91. Root README contains no governed_mcp_demo or demo/governed-mcp-demo link. | Expose the governed synthetic MCP wedge and its exact reviewed-source quickstart prominently, while retaining basic translation as a separate path. Choose the current reviewed pin with its own CI evidence; do not relabel the old evaluator wheel. |
| D03 | docs/README.md:32 — Complete document catalog has94 distinct Markdown targets while104 tracked docs Markdown files exist excluding the index. Ten files are absent, including the governed demo, HA critical path and offline Stripe-style contract. | Add all ten omitted documents and a current engineering/evaluator entry group; keep dated reports clearly identified as historical. |
| D04 | docs/README.md:124 — Link label says Current engineering alpha status - October22,2026; the destination title is November3,2026 and main is now f309a35. | Use a date-neutral Current engineering alpha status label or the actual superseding checkpoint date; do not change historical source pins merely to fix the label. |
| D05 | docs/ROADMAP.md:11 — Current next work includes forced-worker and response-loss recovery trials. docs/HA_CRITICAL_PATH_2026-11-12.md:3-4 records three accepted local forced-stop/acquire-return-loss/renew-return-loss trials. | Record those exact bounded local observations as completed evidence, while keeping actual TCP response loss, partition/rejoin, physical HA, governed-crash acceptance and full-route deadlines open. Add the current prioritization and deferred-until-partner boundary without claiming production completion. |
| D06 | docs/CURRENT_ALPHA_STATUS.md:264 — Current branch count is six after the approved October22 consolidation. The same file's November3 introduction records16 branches. Its historical umbrella at lines17-22 does bound the old count, but the final word Current invites reuse as a live inventory. | Change this sentence to an explicit October22 observation or point to a timestamped current inventory. The root-reported November13 snapshot has21 branch names; their tips remain mutable. Do not delete any branch. |
| D07 | docs/INDEPENDENT_SECURITY_AND_PILOT_REVIEW.md:8 — System-under-test says use the fixed SHA of PR#34 reviewed by the evaluator but supplies no SHA. docs/EXTERNAL_REVIEW_AND_PILOTS.md:8,25 supplies a moving release review branch. The primary OSS kit intentionally installs older d0881b9. | Provide an explicit current source+manifest entry for the new demo/evaluation flow and retain the old wheel/source route as a named historical option. Add exact commands and the matching report template instead of requiring the evaluator to infer a revision. |
| D08 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:93 — All81 IDs and 11 VERIFIED IN CI /4 PARTIALLY TESTED /7 BLOCKED /59 NOT STARTED totals match the Oct25 JSON. Those are explicitly phase-specific historical qualification labels; main and bounded observations have since advanced. | Keep the81 original rows and their dated evidence intact. Add a current source-bound row-by-row assessment with new evidence, remaining acceptance scope, owner and next action. Do not treat NOT STARTED as absence of code or promote native destination/HA claims from mocked or local examples. |

Complete-catalog omissions:

- `docs/ALPHA_PROGRESS_2026-11-03.md`
- `docs/AUDIT_RETENTION_NAMESPACE_2026-11-04.md`
- `docs/GOVERNED_MCP_DEMO_2026-11-12.md`
- `docs/HA_CRITICAL_PATH_2026-11-12.md`
- `docs/HA_FORCED_STOP_AND_LEASE_REPLY_LOSS_2026-11-05.md`
- `docs/HA_RECOVERY_AUTOMATION_2026.md`
- `docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md`
- `docs/HA_WORKER_LIFECYCLE_PREPARATION_2026-10-30.md`
- `docs/MCP_TASK_REFUSAL_2026-11-04.md`
- `docs/OFFLINE_STRIPE_STYLE_CONTRACT_2026-11-12.md`

November3 ALPHA_PROGRESS and October22 historical sections preserve valid source-specific pins/counts. They need superseding navigation, not rewritten history. The81uniqueOct25ledgerrows and totals11CI/4partial/7blocked/59not-started are internally consistent at their original cutoff. A current row-by-row qualification register remains internal work. Existing checker exited0 at exactf309, no missing local targets. Follow-up syntax inventory:405inline links/images,330local/75external,0reference-style links/definitions,0local fragment links,1rawHTML remote src. External URL availability is not accepted from this file-target check.

## Pin verification boundary and remaining artifact work

118tracked documentation text files yielded449occurrences under the recorded extraction grammar:166uniqueGitpins,27uniqueworkflowruns,91SHA256occurrences/65uniquedigestvalues. Every Git object resolves;160are commits already ancestors of f309 and6are trees. This verifies identity/type/reachability, not every prose behavioral claim. All27run metadata rows were re-read; the only failed run is deliberately retained historical7a10a5f.

Expanded prose scan additionally found artifact13205471234 at ALPHA_PROGRESS_2026-11-03.md:18. The run41580327205artifactcollection confirms nameagentbridge-stale-leader-drill, head44a06c3, notexpired, archive digest6489d015c6c2604d7edbaeec2c57990e1eb33a299124a966a28ba60866483a46. This follow-up verifies metadata mapping, not archive contents.

The65historical receipt/source/bundle/wheel/image SHA256values below have been inventoried, not all rehashed. **PARTIALLY TESTED**: internal engineering must locate original immutable bytes, compare digests and examine the matching claim before qualification. Do not silently replace an old artifact with new output. No missing historical evidence is converted into success. Full machine-readable pin/source contexts and run metadata are retained in `work/doc-pin-audit-20261113/verified-inventory.json`; evidence does not depend on a moving branch ref.

## Exact next work and acceptance ownership

| Priority / requirement | Status | Responsible party | Next action / required evidence |
| --- | --- | --- | --- |
| P0 coherent Pydantic floor/hash lock | NOT STARTED | Internal engineering | Narrow current-main unit; clean hash-required install, negative/SDK regressions, exact-head fullCI; owner merge approval |
| Current docs/index/README discrepancies | NOT STARTED | Internal engineering | One current entrypoint, preserve historical pins, catalog all docs, runnable governed demo, checker |
| #92 and remaining dependency integration | PARTIALLY TESTED | Internal engineering / owner | Review action-major compatibility and current-main merges; fresh exact-head CI; explicit merge authorization |
| Missing label correction | NOT STARTED | Maintainer | Prepare exactci/dependenciesmetadata correction or narrowconfigPR; applicable authorization |
| MCP container negatives / transitive closure / optional framework | PARTIALLY TESTED | Internal engineering | Real isolated denied/lostACK/error/timeout/replay/concurrent runs; full container hash lock; optional existing helper reuse |
| Offline mock aggregate capacity/history | NOT STARTED | Internal engineering | Bound bytes/records/entries transactionally; concurrent saturation and UNKNOWN/history negatives; no eviction/replay/refund |
| Validator / design-partner kits and issue drafts | NOT STARTED | Internal engineering | Pinned native/Compose route, feedback/consent/security scope; local timings not independent evaluation |
| Every historical digest semantic acceptance | PARTIALLY TESTED | Internal engineering | Locate original bytes for65digests; preserve explicit unresolved scopes; no blanket production acceptance |
| Legacy semantic/doc parity and Issue38 | PARTIALLY TESTED | Internal reviewer / owner | Map each5commit behavior to current implementation/tests; owner accepts archival; protect/delete decisions separate |
| Native enforcing destination / independent observer | BLOCKED | Consenting operator / external reviewer | Actual destination-atomic epoch capability and separately administered authoritative readback; mocks/Stripe test UI insufficient |
| AWS cluster trial / combined mTLS/CNI traffic | BLOCKED | Owner / cloud operator | AWS owner hold; no spend or auth renewal assumed; retain earlier CNI vs new AWS distinction |
| PhysicalHA / actual return loss / active migrations | PARTIALLY TESTED | Internal engineering / operator | Bounded forcedstop/methodreturnloss accepted only; real partition/rejoin/physicalfence/repeatedRPO/RTO remain |
| Release provenance / published install | PARTIALLY TESTED | Engineering / trusted release operator | Actual published installation/signature+SBOM+trust rotation/rollback; no release or SLSA-level claim |
| Protocol full lifecycle / performance fullroute | PARTIALLY TESTED | Internal engineering | Pinned actual wire versions; unsupportedrefusal;15minfullrouteCPU/RSS/fairnessload, not local SLO |
| 3developers /5buyers / independentsecurity / writtenpilot | BLOCKED | Independent consenting people | Return actual reports/interview records/review/acceptedagreement; invitations and indicative quotes are not acceptance |
| P35 replay-capacity candidate | BLOCKED | Separate required reviewer | Untouched; do not incorporate isolated candidate |
| Branch deletion / new main merges / releases / correspondence | BLOCKED | Owner | Concrete reviewed exact action needs applicable separate explicit authorization |

No requirement is marked PRODUCTION ACCEPTED or EXTERNALLY ACCEPTED. Existing signed queued intent, private preparation, atomic accounting, tenant governance and fail-closed production controls remain the baseline. No new runtime tests were run for this metadata audit; existing source-bound results are reported separately. New local changes must receive their own tests and commit evidence.

## Appendix A — every unique Git pin and its source locations

| Pin | Object | Ancestor of f309 | Source locations |
| --- | --- | --- | --- |
| 01376a59f13e7c4104ff0d2c507473ae334a9422 | commit | True | SECURITY.md:12; docs/CURRENT_ALPHA_STATUS.md:42 |
| 01a7d8a52f | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:24 |
| 01a7d8a52f3f2d36f6b44dec8c2572ac79af32bc | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:35 |
| 06538c52 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:72 |
| 06538c52d7b6f797a0dccbaef0c519da5d819618 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:29 |
| 06be04ac22 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:37 |
| 06be04ac2242b79e2e8d3c21b7c6d942145f38af | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:48 |
| 07303af | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:56; docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:85; docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:105 |
| 07303af2 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:71 |
| 07303af24857322c59c02977dbcca67d74e91d8f | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:16; docs/CURRENT_ALPHA_STATUS.md:104 |
| 08355255ee3fc96461d3d33942cb8f730e8d924b | commit | True | docs/CURRENT_ALPHA_STATUS.md:34 |
| 0d2232ade436ad86ccede04deecf51a144bc204a | commit | True | docs/AWS_REAL_STAGING_TEST_2026-10-13.md:33; docs/P0_P2_OPERATED_ACCEPTANCE_PACKET_2026.md:26 |
| 0eb2887a96 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:44 |
| 0eb2887a969bbc3f2e53ed197383508e881a2528 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:56 |
| 10393374e1cb05778b70eb5ddde65d343ff79a50 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:27; docs/CURRENT_ALPHA_STATUS.md:93 |
| 143c93d | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:60 |
| 143c93d9d4230c3604c976563a6d1b228c0dae30 | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:14 |
| 1efbac5 | commit | True | docs/LEGACY_BRANCH_RECONCILIATION_2026.md:10; docs/RC_INTERNAL_COMPLETION_AND_NOGO.md:256 |
| 228398ca | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:65 |
| 228398ca9a0d95d49b4fbea9d0468998e1a10ff7 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:22; docs/CURRENT_ALPHA_STATUS.md:98 |
| 23b3d004 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:63 |
| 23b3d00413f4331ea949edc70560d2d9962eefe7 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:24; docs/CURRENT_ALPHA_STATUS.md:96 |
| 27321de | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:82 |
| 27ecae3 | commit | True | docs/RC_INTERNAL_COMPLETION_AND_NOGO.md:210 |
| 2b7c675d8f2c254ab0d52b6b1bcb7a0cf3900ab7 | commit | True | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:166 |
| 2c0220d | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:10 |
| 2d0465fd244eb5c0238e35d8b2d0d3cf4eaa5c6b | commit | True | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:164 |
| 3087e35b0b49db5e8cb0406f122aef1f10431395 | commit | True | docs/NEXT_PHASE_EXECUTION.md:121 |
| 31d323c | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:10 |
| 31d323c22c4f8806104fb101352bbb623e80c12f | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:9 |
| 33056f0753 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:29 |
| 33056f0753ad49730c8d5dc70ef6b926590bcaa8 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:40 |
| 34150a901b | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:32 |
| 34150a901b2ee4e640e9294d67476db41a2b7af9 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:43 |
| 347ac442a2 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:47 |
| 347ac442a227a5796b42fecbf604a3d76b16cfa4 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:59 |
| 34d144c | commit | True | docs/CHECKPOINT_CAPACITY_2026.md:14; docs/CHECKPOINT_CAPACITY_2026.md:184 |
| 3560f51dcc | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:30 |
| 3560f51dcc5f0ba7bee836dc32c81a62bf302ea3 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:41 |
| 35f37222597341d2c23e9cd9d0baddf1e36f99f7 | commit | True | docs/AUDIT_RETENTION_NAMESPACE_2026-11-04.md:4; docs/GOVERNED_MCP_DEMO_2026-11-12.md:5; docs/HA_CRITICAL_PATH_2026-11-12.md:14; docs/HA_FORCED_STOP_AND_LEASE_REPLY_LOSS_2026-11-05.md:13; docs/MCP_TASK_REFUSAL_2026-11-04.md:8; docs/OFFLINE_STRIPE_STYLE_CONTRACT_2026-11-12.md:9 |
| 36da007c | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:10; docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:11 |
| 37274bc | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:82 |
| 37a1a12c82 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:26 |
| 37a1a12c828debee35e8af62bf413ca23d0ef4ff | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:37 |
| 397b94030c093c7694ae18547bf796362c70e24e | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:8 |
| 3ad0702c6bf5aaf1676af88724956fdb2af38788 | commit | True | docs/REPOSITORY_WIDE_AUDIT_AND_EXECUTION_2026-10.md:13 |
| 3b8a246101e72667e09bf0416a6b8cd307099bd1 | commit | True | docs/ALPHA_PROGRESS_2026-11-03.md:9; docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:9; docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:55 |
| 3bec61ae20 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:31 |
| 3bec61ae2013baf2b5563f97598d113c0315f17b | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:42 |
| 423a6893 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:59 |
| 423a6893e6c77a8212f8a1fe37d5e91c8745db04 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:28; docs/CURRENT_ALPHA_STATUS.md:92 |
| 44a06c3 | commit | True | docs/ALPHA_PROGRESS_2026-11-03.md:15 |
| 44a06c364e348966e0b14c724f14e3a14d192433 | commit | True | README.md:22; docs/ALPHA_PROGRESS_2026-11-03.md:5; docs/CURRENT_ALPHA_STATUS.md:4 |
| 4604adc | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:81 |
| 4604adcd10aa4ea0550f8b0208d8fe7b020d4565 | commit | True | docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:139; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:140; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:141; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:142; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:165 |
| 46777f8 | commit | True | docs/BRANCH_LIFECYCLE.md:5; docs/CURRENT_ALPHA_STATUS.md:36; docs/OSS_EVALUATION_KIT.md:22 |
| 46777f8c953690fca81c6d11e7b70372b8dd5c77 | commit | True | SECURITY.md:12; docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:10; docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:15; docs/CURRENT_ALPHA_STATUS.md:31; docs/CURRENT_ALPHA_STATUS.md:105 |
| 47d23c6a02 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:28 |
| 47d23c6a027a45af18bab18bc9546384f804b42a | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:39 |
| 483bc982 | commit | True | docs/OSS_EVALUATION_KIT.md:42 |
| 483bc98234ced2b876a6b296a1e1fd292747942c | commit | True | docs/EXECUTION_PLAN_2026-10-14.md:22; docs/OSS_EVALUATION_KIT.md:123 |
| 4892b37a | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:70 |
| 4892b37a72a6a11a346fe5b3347d708bf26e226e | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:17; docs/CURRENT_ALPHA_STATUS.md:103; docs/TASK_EVENT_CAPACITY_2026-10-16.md:3 |
| 4aea2a80b5 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:25 |
| 4aea2a80b574b82949f23616fded48a082c9ed58 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:36 |
| 4db3cc1 | commit | True | docs/LEGACY_BRANCH_RECONCILIATION_2026.md:12; docs/RC_INTERNAL_COMPLETION_AND_NOGO.md:258 |
| 50e8b19be0b3e039fc424513f7c0229678ff6b60 | commit | True | docs/CHECKPOINT_CAPACITY_2026.md:156 |
| 51e3f4c6 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:61 |
| 51e3f4c6f9c85371ec0a2339b312f78823b26a40 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:26; docs/CURRENT_ALPHA_STATUS.md:94 |
| 55b792a38f2aa3c210f0ecb0ca70b6148cf40cb6 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:53 |
| 573826fc | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:69 |
| 573826fcb29039e9438ea5a8746a21faf9f7b409 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:18; docs/CURRENT_ALPHA_STATUS.md:102; docs/TASK_HISTORY_CAPACITY_2026-10-16.md:3 |
| 5af3903f0d | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:42 |
| 5af3903f0d17f8b19a66d42c7eedd93489f67a56 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:54; docs/BRANCH_REVIEW_2026-10-13.md:68 |
| 5cad91f583f935af30de92f7bcdc9fa1b1b4b568 | commit | True | docs/NEXT_PHASE_EXECUTION.md:183 |
| 5cc7606032 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:39 |
| 5cc7606032c89fbcbe112f1c183083623bdc58e6 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:51 |
| 609df6d66446ee9cf8b1acceb3d8f0461dab6e22 | commit | True | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:4 |
| 619d384444 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:27 |
| 619d38444484466be8546b6dde2478f50a160414 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:38 |
| 635288a | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:60 |
| 635288a76750bcd01d9fc9268dd9fe29897b269a | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:15; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:4; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1163 |
| 66a11304141ab17265d6a667803c37994e2300c7 | tree | tree object | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1166 |
| 6771be7 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:81 |
| 6be4bbf8d0027a7965fe65a3f4525aabb50f25ab | tree | tree object | docs/HA_WORKER_LIFECYCLE_PREPARATION_2026-10-30.md:5 |
| 6fab0dd | commit | True | docs/ALPHA_RELEASE_SCOPE_AND_ROLLBACK.md:22 |
| 6fab0dd798e2e625d8aa33af4f718a75ba0b7455 | commit | True | docs/INTEGRATION_SECURITY_REVIEW_2026.md:28; docs/OSS_EVALUATION_KIT.md:146 |
| 735e92479427bc12a8b9f04d2454b7a7ec1a6776 | commit | True | docs/PERFORMANCE_BASELINE_2026.md:3 |
| 73aafd60 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:58; docs/CURRENT_ALPHA_STATUS.md:64 |
| 73aafd60a0eec121a10245a307a4a8ee268f7ed5 | commit | True | SECURITY.md:12; docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:30 |
| 7415718eef8b9650875885ab17eb4d15acf3489b | commit | True | docs/BRANCH_CONSOLIDATION_2026-10-22.md:7; docs/CURRENT_ALPHA_STATUS.md:29 |
| 779e81e | commit | True | docs/LEGACY_BRANCH_RECONCILIATION_2026.md:14; docs/RC_INTERNAL_COMPLETION_AND_NOGO.md:259 |
| 779e81ed | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:73 |
| 779e81ed65 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:43 |
| 779e81ed6571384783310cb9e5d9bb7b71412639 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:31; docs/BRANCH_RECONCILIATION_2026-10-14.md:55 |
| 7a10a5f | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:64 |
| 7ee8252c | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:64 |
| 7ee8252c814c4f9e4f20440951eac4a00938757d | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:23; docs/CURRENT_ALPHA_STATUS.md:97 |
| 893fdba | commit | True | docs/CURRENT_ALPHA_STATUS.md:79 |
| 893fdba4d3d1928bd66491affcb87e01a263b063 | commit | True | docs/CURRENT_ALPHA_STATUS.md:33; docs/QUEUED_INTENT_PREPARATION_2026-10-18.md:188 |
| 89b1cc3 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:81 |
| 8ab8ff3c | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:68 |
| 8ab8ff3c16d3859a6ff86ea4e66154332fa2d1e4 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:19; docs/CURRENT_ALPHA_STATUS.md:101; docs/TENANT_POLICY_PUBLICATION_2026-10-16.md:3 |
| 8b2ed82 | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:10 |
| 8d3230e4f8 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:36 |
| 8d3230e4f8c99b021edd60b9ec13bde10371df2f | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:47 |
| 8fa5c47a6a | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:40 |
| 8fa5c47a6aae3f291fe0fd6198fe8641e648d9f0 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:52 |
| 9006a0b | commit | True | docs/LEGACY_BRANCH_RECONCILIATION_2026.md:13; docs/RC_INTERNAL_COMPLETION_AND_NOGO.md:259 |
| 9aaf6a1 | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:59 |
| 9aaf6a1a0a460d3824ad2966a57f8c5f575bdfae | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:8; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1154; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1164; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1300; docs/EXTERNAL_DESTINATION_FENCING_2026.md:5 |
| a68c53c | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:10 |
| a74f515ab7 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:33 |
| a74f515ab744b9b765231a7005dde1722ce6258d | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:44 |
| ad963a97f8c05c102cbf102ac865f6634553cc0c | tree | tree object | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1258 |
| adcf2a2ea4 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:38 |
| adcf2a2ea4fc1c26a79f03095053ed19d89282f8 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:49 |
| b0afb7f | commit | True | docs/CURRENT_ALPHA_STATUS.md:52 |
| b0afb7f1da1634330747389e19c896fd7002bd83 | commit | True | README.md:82; docs/BRANCH_CONSOLIDATION_2026-10-22.md:8; docs/CURRENT_ALPHA_STATUS.md:28 |
| b123faa45279b0306296ecb3f2c9c9949ad37269 | tree | tree object | docs/BRANCH_CONSOLIDATION_2026-10-22.md:10 |
| b3443d7a20 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:49 |
| b3443d7a209d89f8d8527160e571d6e8d568e647 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:61 |
| b626a6b12daa04146227b9c97f336958fdbe3e9a | commit | True | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1120 |
| b94e2cf | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:91 |
| b94e2cf7ab8281522af76e3dc6d3d0539392a6cb | commit | True | docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:8; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:33 |
| b9fe952af2e9b92bb98c275315a426213d7c5eb5 | tree | tree object | docs/ALPHA_PROGRESS_2026-11-03.md:5; docs/CURRENT_ALPHA_STATUS.md:5 |
| bf6f3fb0c1bbb4fc5c281648f55d845d4b88d044 | commit | True | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1256 |
| c0dc454 | commit | True | docs/RC_INTERNAL_COMPLETION_AND_NOGO.md:204 |
| c154b28 | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:59 |
| c154b28c34cfeab927753e51b93595cc1b485810 | commit | True | docs/CHECKPOINT_REGISTRY_2026.md:10; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1068; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1069; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1161; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1205; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1227; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1257; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1298; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1302; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:3; docs/EXTERNAL_DESTINATION_FENCING_2026.md:5 |
| c4fe9a4 | commit | True | docs/ALPHA_PROGRESS_2026-11-03.md:14 |
| c4fe9a4f9fa1fd58589bd2f3a9c27e734fe29e7f | commit | True | docs/ALPHA_PROGRESS_2026-11-03.md:9; docs/CURRENT_ALPHA_STATUS.md:6 |
| cc705be | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:81 |
| cc705be8ff | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:41 |
| cc705be8fff535883eee2876c88b0cca4e54da61 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:67; docs/CURRENT_STATUS_2026-10-13.md:9; docs/PUBLICATION_STATUS_2026-10-14.md:10 |
| d0881b93 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:66 |
| d0881b937d2568e4e01fb02044bf466aea609e9a | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:21; docs/CURRENT_ALPHA_STATUS.md:35; docs/CURRENT_ALPHA_STATUS.md:99; docs/OSS_EVALUATION_KIT.md:9; docs/OSS_EVALUATION_KIT.md:34; docs/TASK_ATOMIC_SCOPE_2026-10-16.md:3 |
| d0a84fa | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:10 |
| d0a84fae32592f2bad6117a9b305d44d3ef77726 | commit | True | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:9 |
| d3a6072 | commit | True | docs/CHECKPOINT_CAPACITY_2026.md:93 |
| d4a2a4b | commit | True | docs/LEGACY_BRANCH_RECONCILIATION_2026.md:11; docs/RC_INTERNAL_COMPLETION_AND_NOGO.md:257 |
| da3be09367 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:48 |
| da3be09367eaabf759897847025e8f7e96625e8f | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:60 |
| da4e6b42 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:75 |
| da4e6b4280 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:46 |
| da4e6b4280602e2d20d3b7f092c8dbae908f132e | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:33; docs/BRANCH_RECONCILIATION_2026-10-14.md:58 |
| de1194a0b568c820205ac0abaa7f774eb530ae83 | commit | True | docs/CURRENT_ALPHA_STATUS.md:32; docs/CURRENT_ALPHA_STATUS.md:180; docs/QUEUED_INTENT_PREPARATION_2026-10-18.md:105 |
| e0521ad67d7f05e4bec55685cdbb91c96fd158f0 | commit | True | docs/HA_RECOVERY_AUTOMATION_2026.md:6; docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:165 |
| e5c074acd548e746d9bdd282b78033fa58bbd3ee | commit | True | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1125; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1306 |
| eb2dcea8 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:67 |
| eb2dcea8d722def931b95f15a8767d2592c54ad6 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:20; docs/CURRENT_ALPHA_STATUS.md:100; docs/SQLITE_ATOMIC_MUTATIONS_2026-10-16.md:3 |
| ec09fbb86e15a2fa5fbceb8ac67acbd77098897a | tree | tree object | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:9 |
| ec1754bc57db4a7835163c82796b83a6cc6d6200 | commit | True | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:13; docs/HA_WORKER_LIFECYCLE_PREPARATION_2026-10-30.md:5 |
| ef02aeff60 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:34 |
| ef02aeff609df76fa67432157b2d79a70e865a76 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:45 |
| f108dce057a157fb61c6f635dfef4939fdc34fe4 | commit | True | docs/LEGACY_BRANCH_RECONCILIATION_2026.md:4 |
| f1c75d06 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:74 |
| f1c75d0687 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:45 |
| f1c75d0687aa8d1e690539ec858aef171d26df01 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:32; docs/BRANCH_RECONCILIATION_2026-10-14.md:57 |
| f2629d2b | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:62 |
| f2629d2baf23ff83cbbe7c43dc7257c63639cc93 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:25; docs/CURRENT_ALPHA_STATUS.md:95 |
| f76338fef677a7fe6a3923aa9ec53045fcbb4759 | commit | True | docs/TENANT_RUNTIME_2026-10-14.md:91 |
| fab51e83f3 | commit | True | docs/BRANCH_REVIEW_2026-10-13.md:35 |
| fab51e83f37f5b9e740c0605bc70968e68f5d171 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:46 |
| fe69425 | commit | True | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:81 |
| fe694256ce7b9253af8e1778b6ec7634117803d1 | commit | True | docs/BRANCH_RECONCILIATION_2026-10-14.md:50 |

## Appendix B — every documented workflow run

| Run | Exact head | Conclusion | Source locations |
| --- | --- | --- | --- |
| 38358713825 | 0d2232ade436ad86ccede04deecf51a144bc204a | success | docs/P0_P2_OPERATED_ACCEPTANCE_PACKET_2026.md:26 |
| 38501709996 | 483bc98234ced2b876a6b296a1e1fd292747942c | success | docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:35; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:36; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:66; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:67; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:68; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:69; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:70; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:71; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:77; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:79; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:80; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:81; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:87; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:88; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:89; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:90; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:91; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:92; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:93; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:94; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:101; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:102; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:103; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:104; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:105; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:106; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:107; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:113; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:114; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:115; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:116; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:117; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:118; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:124; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:125; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:126; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:127; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:128; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:148; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:149; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:155; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:156; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:157; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:166; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:167; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:168 |
| 38523645310 | 4604adcd10aa4ea0550f8b0208d8fe7b020d4565 | success | docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:134; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:135; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:136; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:137; docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:138 |
| 38525405374 | 37274bcafee056089904eb2c9342e51cb473b74c | success | docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:164 |
| 38526259932 | b94e2cf7ab8281522af76e3dc6d3d0539392a6cb | success | docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:33 |
| 38846044004 | d0881b937d2568e4e01fb02044bf466aea609e9a | success | docs/OSS_EVALUATION_KIT.md:12 |
| 38991859007 | 46777f8c953690fca81c6d11e7b70372b8dd5c77 | success | docs/CURRENT_ALPHA_STATUS.md:68 |
| 38991859072 | 46777f8c953690fca81c6d11e7b70372b8dd5c77 | success | docs/CURRENT_ALPHA_STATUS.md:69 |
| 38991859150 | 46777f8c953690fca81c6d11e7b70372b8dd5c77 | success | docs/CURRENT_ALPHA_STATUS.md:70 |
| 38991859193 | 46777f8c953690fca81c6d11e7b70372b8dd5c77 | success | docs/CURRENT_ALPHA_STATUS.md:67 |
| 39013120802 | de1194a0b568c820205ac0abaa7f774eb530ae83 | success | docs/CURRENT_ALPHA_STATUS.md:181; docs/QUEUED_INTENT_PREPARATION_2026-10-18.md:107 |
| 39116757207 | 893fdba4d3d1928bd66491affcb87e01a263b063 | success | docs/CURRENT_ALPHA_STATUS.md:81 |
| 39399999492 | 08355255ee3fc96461d3d33942cb8f730e8d924b | success | docs/CURRENT_ALPHA_STATUS.md:85 |
| 39706489270 | 7415718eef8b9650875885ab17eb4d15acf3489b | success | docs/BRANCH_CONSOLIDATION_2026-10-22.md:12 |
| 39736688053 | b0afb7f1da1634330747389e19c896fd7002bd83 | success | docs/BRANCH_CONSOLIDATION_2026-10-22.md:10; docs/CURRENT_ALPHA_STATUS.md:53 |
| 39884970368 | ccdd1a57064ca02915912562779e2de2c998e3de | success | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:76 |
| 39928339316 | d3a6072b4436e588caacfd95d08bddfb88b1463e | success | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:88 |
| 39968001623 | 5b6981e284af11a1ab32f04ac052b4ac8b8ee27b | success | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:100 |
| 40046824359 | 7a10a5f9683606f86d17d63891cf9f19acf59599 | failure | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:112 |
| 40068956312 | 143c93d9d4230c3604c976563a6d1b228c0dae30 | success | docs/CHECKPOINT_REGISTRY_2026.md:17; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:113; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:126; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:140; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:154; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:168; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:227; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1019 |
| 40070457044 | 635288a76750bcd01d9fc9268dd9fe29897b269a | success | docs/CHECKPOINT_REGISTRY_2026.md:19; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:5; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:127; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:141; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:155; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:169; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:228 |
| 40161311373 | 9aaf6a1a0a460d3824ad2966a57f8c5f575bdfae | success | docs/CHECKPOINT_REGISTRY_2026.md:9; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:186; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:208; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:230; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:252 |
| 40187737269 | c154b28c34cfeab927753e51b93595cc1b485810 | success | docs/CHECKPOINT_REGISTRY_2026.md:11; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:188; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:210; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:231; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:254; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1173; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:3; docs/EXTERNAL_DESTINATION_FENCING_2026.md:5 |
| 41283398658 | 3b8a246101e72667e09bf0416a6b8cd307099bd1 | success | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:9 |
| 41455144424 | c4fe9a4f9fa1fd58589bd2f3a9c27e734fe29e7f | success | docs/ALPHA_PROGRESS_2026-11-03.md:14 |
| 41580327205 | 44a06c364e348966e0b14c724f14e3a14d192433 | success | docs/ALPHA_PROGRESS_2026-11-03.md:15; docs/CURRENT_ALPHA_STATUS.md:5 |
| 41638001805 | 35f37222597341d2c23e9cd9d0baddf1e36f99f7 | success | docs/MCP_TASK_REFUSAL_2026-11-04.md:67 |

## Appendix C — every distinct historical non-Git digest, pending original-byte reconciliation

Every row has status **PARTIALLY TESTED**, responsible internal engineering, next action locate original artifact/version and verify bytes plus contextual claim. These are explicit remaining evidence tasks, not refuted hashes.

| SHA256 | Source locations |
| --- | --- |
| 09318d0f894747851a7b1f179eb559570c80340e5fac08134c5370da2bacb2f8 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:51 |
| 0e5ca37c1eaf06911e4f87f071c1853ceb0608d96c744cfa84504c84821f62b0 | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:150 |
| 0ff031fc33071a6f3f51ff72f707c89dcc5947ec6c9541bc2f70084cbd41b5e0 | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:48 |
| 1675dc2e566d2a92d0461c90cd55a146a4ebb2b864f2b12771c25759f8ec41dd | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:59 |
| 1d2b09aa5c1ed447fccd94c77e5da1d6039cedfe9a74155ab7cf9ff7031ea781 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:17 |
| 2170c80bae139d47060df31de6bb4d1134636eec1407db12a384444dca9f5c27 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1213 |
| 2367045ebfbe0fa502d4f8f59183696181834a847d2d309f1894e48667deb703 | docs/CURRENT_ALPHA_STATUS.md:36 |
| 244547b11052ddc327754df570b51757b02de69e516e4ccf353e1195e42cb659 | docs/OFFLINE_STRIPE_STYLE_CONTRACT_2026-11-12.md:140 |
| 28805f5d99d8ed944c5a3a8a84f2da4d770f28eb63b58ef5bc67815a4bca0395 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:187; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:209; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:253; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1158 |
| 2ec87a77918a75c63f8f979202113d663d1eea378caef92d50a3f8cfa79d8f0f | docs/HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md:34 |
| 3391f06654e13934fdafec7a42f89fa6a8cd49ca9306d080eabdc2ed3351c99b | docs/QUEUED_DISPATCH_AND_RECOVERY_2026-10-22.md:30 |
| 34404d6714ba345a20ae10b9dbd9f706da15279bb38dfa865221f68a5fe6f6d9 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:19 |
| 3567f576cbaa73aad925139f7c9ff161e76f3e5569872ed257032e6813076700 | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:32 |
| 3cf9c681b3e7a5d75cddbc344e6fe092c21b458f3d854327d1931146ed9ae63d | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:13 |
| 40c10a2b63d3f4c47e2045450a979f3172eb550691999364b509e223bbfa21e1 | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:194 |
| 428efe2382cb853285616883ddae330946fc63731778bb6b095ba77095475b54 | docs/CURRENT_STATUS_2026-10-13.md:88 |
| 444c101f407d55b904743d0997bb6dc7c3179babb74824f882a00ecfb5363d83 | docs/CHECKPOINT_CAPACITY_2026.md:155 |
| 4ccd8badac6d98d50aef3634f44dbf6104be0914203912743721ea6c9f572025 | docs/HA_RECOVERY_AUTOMATION_2026.md:136 |
| 4eda32341be9bec4397ca51948758c6dd0ce0e12745ce0a5306174a4e3ef9f0a | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:389; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1232; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:95 |
| 5052bbe3dc90a9362db183d3dfd014b1e8406b74f9f87c7c3251a3eeef72d155 | docs/OFFLINE_STRIPE_STYLE_CONTRACT_2026-11-12.md:139 |
| 59209ce12490424e58f4b6693b788a1a39b7617b157293f2450ed94a52fe423c | docs/HA_CRITICAL_PATH_2026-11-12.md:9 |
| 5cd7ffe0dfedc0422efc4f6960524a9e939ae090a23fdfd6da7840e35f420377 | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:196 |
| 6019145869655015e5d899736f6b9cce6645e240d7128541f2435ef15ce5afbd | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:190; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:212; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:233; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:256; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1175; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1313 |
| 60b47ba6d5a3845dc785e3928039570c5ffb7148e9a711443c6d61f1e2299e69 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1219 |
| 6141a1ff8ec14469ca53212571a473e88dbae51687bd89631d11e5a19b653d72 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:20 |
| 64e4702d2e5e122017b12914ad10f3dbfb72f4c40f3d3495b624d058d2580239 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:419 |
| 6e6e57032dae6ddb529faf383db95c08507255c5187ea05ac7dcd9bb10c6fc10 | docs/HA_RECOVERY_AUTOMATION_2026.md:133 |
| 6f4d803a59fdeee2767ff434d2a34fb6f6b56a779748de8951546d4850e0d4af | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1184 |
| 7d9803efaa39a0890ff8856179f0fbdfd60352c89331a05ffa46db502e958dad | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:192; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:214; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:235; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:258; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1179 |
| 7dc53620e162f82a08c5383e47d7cc77918341fca5575a4ad5ef1218a3e46c95 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:59 |
| 7faec790f20bf2748d1e0801c5e87f6aa6b985a972e10a74aa6a257dc2b2780f | docs/HA_CRITICAL_PATH_2026-11-12.md:110 |
| 7faf948c0c78e65c65f528de796c7a50e27e949db8d9d2fc7f9abc5cf1d75279 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:51 |
| 80d1ad2b6621669fb5e9ae2bb7cc177f2fb7556f6f6065aa7b54ac484a948781 | docs/HA_RECOVERY_AUTOMATION_2026.md:137 |
| 8186189fc644f98459085ed2a6506e90a88dc860a07266d4be4f9e5ce46eb07c | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1144; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1192 |
| 89c96b47343a9b75c8b305db96bef77bd1d9c6d839233a0ae8d9e2336bd28bef | docs/CHECKPOINT_CAPACITY_2026.md:158 |
| 8d564b5ddb29ca771e883df41b3f605ef6aa9996369ca6f99ea6780854acf1f8 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:48 |
| 90ea9214ae0c6d71606b20cf6c7bc9a6b41ab323fd92af76666bd6a9a7f66a71 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1259 |
| 9137a797200195b604287485af413d1f6c06de39bee03fa305869809946f4a2f | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:49 |
| 9322689efcd65de8deb01f0f554dcbb12aa8520158ef0f5699db3f083afcfdab | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:21 |
| 997f88200a8a36734ca322be0cd6af96f123f3302bc6e53ffa0945ea9ebec0b6 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1277 |
| a61deb16722eec465f8f58ae3ffd01b5860cc75d008d18b1aa2b10d592a76bf5 | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:152 |
| a8adb1dbd6226c6ee89c43ba5cdc9afb6af09994dbb5f9628d88a81af527f898 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:420 |
| aec7a50d69f3217c23c4d1456af9e3d85e4bf49454e7041692fa4c8106506dcc | docs/AWS_TWO_HOST_QUALIFICATION_2026-10-13.md:49 |
| af8baac756b6cfc5eb281cdf83dbd88d2775e12b7ed45e259a47464e45b72947 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:421; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:423 |
| b2bf23947d6815bb7891494404c0f355073d8192d3ac5e2939fe6fce342e83af | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1251; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:101 |
| ba76b9a7fdd0d100d93c1005c86846c5dba76e7dde84d6db99472ee88e08eb31 | docs/CURRENT_STATUS_2026-10-13.md:72 |
| bc8b0dae2a34ce9d5d96d424e78f1e650a670ac07b9b2cddc377f80d734cd743 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:18 |
| bd2778e1b3c6721269f4eb467184dd7703d6128dba2310a4d74ad01ea2fd80b6 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1104 |
| bed749ea145519a61077c81383409b838aba19b2e264913fbca7a2e7376f469b | docs/BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md:100 |
| c7c5cca79fb91ee3013943b18ce537c03aab1f6463dccd2fcff4f39153c6d893 | docs/CHECKPOINT_CAPACITY_2026.md:177 |
| cbc1b149c6a736c268afdb817d84d5eda4fc6eddc0cde19b7c2b95a489dd6fd1 | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1230; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:95 |
| e06a5a6bbd524fdf35a2d3ca79d0ebeec225dc0e31af9ce9cb6d71ce2c2f8205 | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:192 |
| e104e6321eeeb867b8d5b95be5c37f8f9c2e07c430824c3073b91823fd334156 | docs/CURRENT_STATUS_2026-10-13.md:98 |
| e549c9f16bf7d8e7888c190b301d848113c8208330a1010de87874f5fdde690e | docs/HA_CRITICAL_PATH_2026-11-12.md:112 |
| ec570a45bf4c8c78f6f0f2c6dc6cf4307deb16c2bd74c23ffacb6e1074e1ab43 | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:146 |
| f003ea26fe9cb8c1dc055f41eda9a9787cd10ded0115a07cbc2be847faa1b9a5 | docs/CHECKPOINT_REGISTRY_2026.md:52; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:184 |
| f0b7fd811b5369fa75a1af2a1708e34ddfca1c393cccb3d155f54c1779c89bda | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:144 |
| f26f6ceae7b5adb800f7ae06f44aef33aebb2d657d1bef5a29c70a74dcd41cee | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:388; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1229; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:95; docs/EXTERNAL_DESTINATION_FENCING_2026.md:48 |
| f31d7746fcf0fdad8fa1c296f6723b1cc977cbf78ee46524df8041785f43fe7b | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1099 |
| f38f5fdf8e23e543002be7ab8040385d9f878f8de4ef71479ed0b480dc4f8415 | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:148 |
| f4e47e45a467a12c11a90cfd7e71196f9ae1f5dcea84296ff07e48df5c4f7dc9 | docs/CHECKPOINT_REGISTRY_2026.md:53; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:183 |
| f5d933c166ea51d17d46a51f24e81141f0ba7ed71bb656232d11b4b4f90e954b | docs/RECONCILIATION_EVIDENCE_CAPACITY_2026-10-26.md:198 |
| f68b5ad9db37d86e9b48d44df819ed0b74b51600daa8be678619f1d0d0f69f6a | docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:387; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.json:1231; docs/ENGINEERING_PHASE_PROGRESS_2026-10-24.md:95; docs/EXTERNAL_DESTINATION_FENCING_2026.md:48 |
| fc53f5f4ee9a17f67047595f075b1ce2b8073103e6851480edb477e44e869327 | docs/HA_WORKER_LIFECYCLE_CONTROLLED_TRIALS_2026-11-02.md:47 |
| fe4f2debe997b4ed047748edec46605ceda0f3c3112f3d80b537282e1df54038 | docs/BRANCH_CONSOLIDATION_2026-10-22.md:17 |

## Retained audit receipts

The maintainer-local evidence set contains `AgentBridge-issues-and-branches-audit-2026-11-13.{json,md}`, `AgentBridge-dependency-audit-2026-11-13.{json,md}`, `AgentBridge-main-f309-CI-2026-11-13.json`, `DOCS_AUDIT_2026-11-13.{json,md}`, `doc-pin-audit-20261113/{inventory,verified-inventory,run-metadata,artifact-13205471234}.json`, and the checker receipt. Public source/run/issue references in this document permit identity checks; private correspondence and personal identity documents are excluded. All raw original failure/refusal evidence stays retained.
