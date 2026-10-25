# Nine-phase engineering checklist and progress - October 24, 2026

Last reviewed October 25, 2026. **PARTIALLY TESTED; production NO-GO.** Baseline main `635288a76750bcd01d9fc9268dd9fe29897b269a` has its own 16/16 hosted success. This supplemental checklist accounts for the new handoff; it preserves older requirements and their source-specific evidence.

Every new phase branch starts from recorded main. Every protected-main merge needs explicit approval. Work proceeds sequentially; a recorded blocker may permit an independent preparation task. NOT STARTED means no new phase acceptance audit yet, not that code is missing.

AWS use was authorized October 25 within USD 100 total. The connector verified active free-plan credits before use; no paid resources have been created for this phase. A cloud trial needs a priced scope and bounded teardown. AWS trials do not establish independent external acceptance.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Checkpoint registry | PARTIALLY TESTED |
| 2 | External destination fencing | NOT STARTED |
| 3 | Network and workload identity | NOT STARTED |
| 4 | HA and recovery | NOT STARTED |
| 5 | Supply chain and release provenance | NOT STARTED |
| 6 | Protocol conformance | NOT STARTED |
| 7 | Performance and operations | NOT STARTED |
| 8 | External validation preparation | NOT STARTED |
| 9 | Documentation and final status | NOT STARTED |

The 81 tasks account for verified existing work and remaining requested items. Evidence, reason, owner and next action are in the [machine-readable progress list](ENGINEERING_PHASE_PROGRESS_2026-10-24.json). Update both from a source-bound review; a file or mock test alone is not acceptance.

| ID | Task | Status |
| --- | --- | --- |
| P1-01a | Verify historical checkpoint source ccdd1a5 | VERIFIED IN CI |
| P1-01b | Verify historical checkpoint source d3a6072 | VERIFIED IN CI |
| P1-01c | Verify historical checkpoint source 5b6981e | VERIFIED IN CI |
| P1-01d | Verify historical 7a10a5f without erasing its failed result | PARTIALLY TESTED |
| P1-02a | Saturation preserves legal holds and UNKNOWN reservations | VERIFIED IN CI |
| P1-02b | Refuse PostgreSQL TEMP and UNLOGGED checkpoint relations | VERIFIED IN CI |
| P1-02c | Real offline restore retains exact checkpoint bytes/policy/holds | VERIFIED IN CI |
| P1-02d | Independent concurrent checkpoint writers cannot exceed capacity | VERIFIED IN CI |
| P1-02e | Reject restored checkpoint raw-text drift even when parsed JSON remains equivalent | PARTIALLY TESTED |
| P1-03 | Document registry limits, no eviction/refund/replay and remaining storage/retention gaps | IMPLEMENTED / UNTESTED |
| P1-04 | Require 24 exact-head hosted jobs and owner approval before checkpoint merge | VERIFIED IN CI |
| P1-05 | Publish source-bound checklist/progress/blockers without production claims | IMPLEMENTED / UNTESTED |
| P2-01a | Audit/reuse existing destination contract before defining ExternalDestinationFence | NOT STARTED |
| P2-01b | Stripe sandbox adapter: verify actual atomic epoch capability before implementation | NOT STARTED |
| P2-01c | Salesforce sandbox adapter: verify actual atomic epoch capability before implementation | NOT STARTED |
| P2-01d | Generic HTTP adapter with fixed operator allowlist and qualified target contract | NOT STARTED |
| P2-02a | Per-service destination-atomic monotonic fencing and allowed effects | NOT STARTED |
| P2-02b | Destination-authored receipt with explicit signer/custody boundary | NOT STARTED |
| P2-02c | Authoritative independent readback of actual destination state | NOT STARTED |
| P2-02d | Idempotency and timeout/lost-ACK handling preserving UNKNOWN without replay | NOT STARTED |
| P2-03a | Mocked API negative tests, split brain and stale leader | NOT STARTED |
| P2-03b | Lost ACK after commit, concurrent resource operations and unauthorized destinations | NOT STARTED |
| P2-04 | EXTERNAL_DESTINATION_FENCING_2026: sandbox support, exact guarantees, config and omissions | NOT STARTED |
| P2-AC | Qualify two actual destination-enforced adapters; mocked API success alone is insufficient | NOT STARTED |
| P3-01 | Audit existing CNI/relay assets; prepare production-candidate NetworkPolicy/mTLS/CNI manifests | NOT STARTED |
| P3-02a | Extend existing workload_identity.py with verified SPIFFE/SPIRE and mTLS contract | NOT STARTED |
| P3-02b | Certificate rotation/drain and per-request revocation checks on every enabled path | NOT STARTED |
| P3-03a | Actual DNS rebinding/private resolution and IPv4-mapped IPv6 refusal | NOT STARTED |
| P3-03b | Metadata endpoints and redirect-chain destination enforcement | NOT STARTED |
| P3-03c | CONNECT framing/smuggling and TLS certificate/SNI negative tests | NOT STARTED |
| P3-04 | NETWORK_ISOLATION_PRODUCTION_2026: exact supported deployments/results/gaps; reference relays sandbox-only | NOT STARTED |
| P3-AC | Operated kind/Calico traffic with identity and fail-closed adversarial evidence; no YAML-only acceptance | NOT STARTED |
| P4-01a | Audit existing fences/recovery before leader-election implementation | NOT STARTED |
| P4-01b | Concurrent election, bounded lease/default 30 s, transfer and destination epoch enforcement | NOT STARTED |
| P4-02a | Actual WAL archive/PITR and checksum plus restored-query verification | NOT STARTED |
| P4-02b | Active-work migration and safe rollback preserving newer data; no automatic data-loss restore | NOT STARTED |
| P4-02c | Split-brain detection and dual-writer prevention at the effect boundary | NOT STARTED |
| P4-03 | ha_drill partition/leader-kill/schema-migration/backup-restore with measured RPO/RTO JSON | NOT STARTED |
| P4-04 | Negative concurrent startup/partition/in-flight restore/migration failure tests | NOT STARTED |
| P4-05 | HA_RECOVERY_AUTOMATION_2026 with methodology/runbooks and bounded manual promotion limitation | NOT STARTED |
| P4-AC | Repeatable old-leader fencing within declared TTL and measured loss/duplicates/UNKNOWN; no invented no-loss proof | NOT STARTED |
| P5-01 | Audit/reuse existing release verification, signing, SBOM and provenance assets | NOT STARTED |
| P5-02a | Reproducible hash locks for all runtime/build/optional transitive dependencies and supported platforms | NOT STARTED |
| P5-02b | Wheel/container CycloneDX SBOM with actual dependency validation | NOT STARTED |
| P5-02c | Trusted cosign identity/key rotation/revocation distinct from ephemeral CI identity | NOT STARTED |
| P5-02d | Reviewed gated PyPI/GHCR publication/attestation; no release is authorized by preparing a workflow | NOT STARTED |
| P5-02e | Assess SLSA build-platform requirements; generated JSON alone cannot establish Level 3 | NOT STARTED |
| P5-03 | Published-artifact verification: signatures, SBOM, provenance and manifest hashes | NOT STARTED |
| P5-04 | RELEASE_PROVENANCE_2026: actual trust roots and current ephemeral CI-only limits | NOT STARTED |
| P5-AC | Negative artifact/dependency/provenance tampering and key rotation compatibility tests | NOT STARTED |
| P6-01a | Pinned A2A 0.3 lifecycle submit/status/stream/cancel/complete | NOT STARTED |
| P6-01b | Verify actual A2A 1.x specification and migration features before claiming support | NOT STARTED |
| P6-01c | Pin actual MCP protocol revisions separately from SDK 1.x/2.x; stdio/Streamable HTTP/SSE | NOT STARTED |
| P6-01d | Official OpenAI parallel-tool and Gemini structured function-call behavior | NOT STARTED |
| P6-02a | Discovery, negotiation, request/result/error and malformed/version mismatch negatives | NOT STARTED |
| P6-02b | Stream/reconnect/resume, task identity, cancellation/timeout and notification semantics | NOT STARTED |
| P6-02c | Authentication/OAuth positive and negative flows | NOT STARTED |
| P6-03 | PROTOCOL_CONFORMANCE_MATRIX_2026: pinned SDK/spec/transport matrix and explicit unsupported semantics | NOT STARTED |
| P6-AC | Official SDK/reference interoperability for each claimed combination; no blanket full-support claim | NOT STARTED |
| P7-01a | Audit existing load/profile tools before translation/admission/settlement/stream workload runner | NOT STARTED |
| P7-01b | Concurrency 1/8/32/128/512 with bounded 5/15/60 min supported runs | NOT STARTED |
| P7-01c | p50/p95/p99, throughput, timeouts/errors, RSS/CPU plus queue/retry/DB contention metrics | NOT STARTED |
| P7-02a | Admission/backpressure with tenant fairness and explicit 429 shedding | NOT STARTED |
| P7-02b | Queue monitoring/thresholds and negative saturation/resource-ceiling tests | NOT STARTED |
| P7-03 | PERFORMANCE_SLO_2026: exact hardware/workload/results; local measurements are not production SLOs | NOT STARTED |
| P7-AC | At least 15 min of measured full-route traffic with defined degradation criteria and no hidden loss/replay | NOT STARTED |
| P8-01 | Reuse existing evaluator/security/interview material; assemble evaluation package layout | NOT STARTED |
| P8-02a | Pinned Docker synthetic lost-ACK evaluator setup and clean-install timing | NOT STARTED |
| P8-02b | Evidence-based Kong/Portkey/LangSmith comparison and specific technical feedback form | NOT STARTED |
| P8-03a | 20-minute buyer script: actual pain/cost/budget/incumbent/permissions/timeline | NOT STARTED |
| P8-03b | Plain-language consent/privacy draft with qualified legal review; do not certify GDPR/CCPA compliance internally | NOT STARTED |
| P8-03c | Follow-up template and response register honoring consent/no-repeat promises | NOT STARTED |
| P8-04a | Existing threat-model/entry-point inventory and STRIDE review-scope reconciliation | NOT STARTED |
| P8-04b | Disclosure and acknowledgment/permission templates without disclosing blocked findings | NOT STARTED |
| P8-05 | Read current issues #36/#44/#33, prepare source-bound acceptance links and reviewed tracking updates | NOT STARTED |
| P8-AC | Independently timed <10 min setup, qualified legal acceptance and independently reviewed entry-point scope | NOT STARTED |
| P9-01 | CURRENT_ALPHA_STATUS exact phase SHAs/tests/CI and bounded qualified/open/NO-GO table | NOT STARTED |
| P9-02 | ROADMAP verified phase dates/dependencies and evidence-based estimates with assumptions | NOT STARTED |
| P9-03 | README evaluator quickstart/architecture/current limitations reconciled with actual source | NOT STARTED |
| P9-04 | COMPLETION_REPORT_2026 with source-bound coverage, gaps and external next steps | NOT STARTED |
| P9-AC | Cross-document consistency with every unmet requirement owned; no production/commercial/certification overclaims | NOT STARTED |

The historical 7a10a5f failure is preserved. Corrected 143c93d success, actual main 635288a success and the new two-case local restore negative are separate evidence. See [checkpoint registry evidence](CHECKPOINT_REGISTRY_2026.md) and [blockers](BLOCKERS.md). PR #73 remains draft-only. General retention, physical disk quotas, independent reviews, legal acceptance, developer/buyer evidence and pilot consent remain open.
