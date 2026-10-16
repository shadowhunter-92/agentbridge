# Authenticated tenant authority foundation — October 14, 2026

This is the first implementation unit after main73aafd60. It does **not** activate
a multi-tenant control plane or declare tenant isolation complete. Existing
single-tenant entry points and the generic production target restriction remain
in place. Storage/runtime/API propagation and safe historical migration are
subsequent, required units.

`src/governance/authority.py` adds an immutable principal context and a durable
SQL authority directory using the existing SQLite/PostgreSQL store backends.
Trusted operator configuration pins issuer verifiers. Explicit one-time setup
enrolls the first platform administrator; login never enrolls an administrator.

Authority distinguishes platform administrators, tenant administrators/operators/
viewers, machine principals and explicitly granted human delegation. Tenant roles
come from operator-controlled enrollment, not a token's self-selected role claim.
Issuer/subject pairs, tenant enrollment, agent keys, memberships, tenant revisions
and delegation revisions remain distinct. A tenant administrator cannot create a
platform administrator or administer another tenant.

The v2 agent signature covers a domain separator, tenant, agent, delegation,
nonce and exact body hash. Tenant/grant values select candidate enrolled records;
they never establish membership. Nonces are claimed atomically in SQL. Contexts
are sealed by the authenticating directory and cannot be serialized/reconstructed
or transferred between worker-directory instances as authentication. Restarted
workers reauthenticate. The context also binds the exact body/nonce and exposes
separate stable authority fingerprint material for operation/approval binding.

Delegation requires an authenticated user context, a scoped administrator, an
enrolled agent and explicit capability/target subsets of both user and agent
authority. Grants cannot outlive the authenticated user context or one hour.
Every use rechecks durable tenant, agent, user, grantor and grant revisions and
expiry. Tenant reactivation does not revive old grants. Machine-only calls do
not invent a human principal. Current authority is checked in SQL; this is not
yet an atomic authorization/effect contract at an external destination.

The additive v1 authority schema is guarded by an immutable DDL digest. Unknown
or changed metadata fails closed. Existing identities, budgets, approvals,
operations, audit bytes and signing evidence are not relabeled or rewritten.
This additive schema is not the historical-data tenant assignment migration.
Replay retention is an explicit bounded platform-maintenance operation and
never removes a still-valid nonce. Durable tenant capacity quotas follow later.

Qualification: `tests/test_authority.py` executed **48 cases on SQLite and
PostgreSQL**, including separate-connection replay races, namespace/issuer/key
confusion, tampering, revision changes, revocation, expiry, bounded scopes and
unchanged legacy data. Before implementation, collection failed because the
new module was absent; this is feature-absence evidence, not a claimed exploit.
The PostgreSQL CI job now explicitly includes these tests. Exact-head CI and
broader runtime/migration acceptance must be recorded before those scopes are
marked verified.

Further units must carry the same authority through direct SDK, HTTP, MCP/A2A,
tasks, exports, evidence and background work; recheck it at approval consumption
and effect boundaries; and test every supported ingress. Until then, the project
remains an engineering alpha and unrestricted consequential-action production
remains NO-GO.
