# Tenant policy publication — October 16, 2026

Baseline: `8ab8ff3c16d3859a6ff86ea4e66154332fa2d1e4` (PR #65,
24 successful hosted checks). Existing durable policy and approval configuration
are reused; there is no additional policy engine or authority implementation.

`TenantSession.mark_sensitive` and `add_policy` previously held an authority
read guard. A PostgreSQL writer could publish while a concurrent admission held
the same shared guard. Policy and its administrative audit also committed
separately on both SQLite and PostgreSQL. Tests reproduced two publication race
failures and four policy/audit rollback failures.

Both methods now take the existing exclusive authority guard and wrap the policy
change plus audit in `sql_atomic` on the tenant's runtime store. Lock order is
authority guard before tenant SQL; no shared-to-exclusive upgrade is attempted.
Current principal/tenant/role checks still precede mutation. Unserializable rules
are rejected by the existing durable policy implementation.

The regression verifies actual PostgreSQL `pg_blocking_pids` relationships between
independent connections. Policy remains unchanged while admission's guard is
held; after publication, new signed requests observe the change. Injected failure
after appending the audit entry rolls both policy and audit back. Negative cases
cover machine/viewer writes and attempted nested read-guard upgrades.

This is a local admission/publication order, not revocation of work already
admitted or atomicity with an external effect. Request preparation may overlap a
publication; final guarded admission observes the current policy. The existing
global authority barrier conservatively serializes administrative publication
across namespaces. It is not a performance/SLO qualification or a replacement
for destination authorization/fencing. Low-level store/policy helpers are trusted
in-process components, not independent authenticated ingress surfaces.

Other operator methods, tenant evidence/reconciliation services, executable task
intent and destination/network/HA/release/full-path performance gates retain
their separate requirements. Unrestricted consequential-action production is
still NO-GO. Exact commit and test/CI receipts belong in the phase report.
