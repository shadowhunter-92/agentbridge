# Current release workflow (draft; no production authorization)

1. Freeze a reviewed commit and record its SHA, dependency locks, SBOM, container digest, base image digest, exact Python/SDK versions and scope of supported integrations.
2. Require successful tests on the **exact commit**, including the offline Trust/Evidence quickstart, PostgreSQL recovery and fencing, CNI enforcement (in actual cluster), protocol reference clients and representative service load. Record artifacts and observed measurements.
3. Check all P0 and P1 gates against real operated evidence: workload-authenticated egress, independently managed read-only observer and key custodian, HA split brain and RPO/RTO, accurate recovery and rollback.
4. Review branch ancestry and conflicts with current main. Do not resolve doc conflicts by blindly replacing newer main files. Prefer a clean integration branch and focused diff review.
5. Produce reproducible wheel/container artifacts using pinned build environment; verify independently signed provenance and artifact hashes, vulnerability scans and installer tests. CI's ephemeral test signatures do **not** establish published supply-chain custody.
6. Run staged upgrades and rollback with synthetic data, versioned DB migrations and verified prior-version support; independently review audit continuity and retention.
7. Obtain explicit independent security acceptance, owner approval, published release notes/known limitations, and supervised pilot authorization for each target.
8. If any gate is absent or fails: **NO-GO**, keep PR draft, preserve branch and evidence, and create specific remediation tickets.

## Current limitations (October 12)

- CI from an earlier head is not interchangeable with the current head.
- Draft PR #34 has diverged from main after independent docs/WAL fixes.
- The project can demonstrate more than its original prototype but does not
  have generic destination-fencing, independent custody or real CNI/HA proofs.
- A public version number or a merge is not an operational safety certificate.
