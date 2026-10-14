# Production destination qualification boundary

The HTTP `/control/route` endpoint rejects named execution targets in `prod` and
`production` until a destination-specific enforcement adapter is implemented and
qualified. Current `mcp_stdio`, `a2a_http` and `acp_http` target kinds are generic
transports. An approved agent, capability, cost schedule, HTTPS origin or proxy
does not prove that the destination atomically enforces the authorized action,
monotonic epoch and unique committed effect.

Rejection occurs during target resolution, before governance admission: no
approval is consumed or requested, no budget reservation/operation claim is
created, and no target transport is invoked. Authentication may still claim the
request nonce, which is intentional anti-replay behavior. A rejected local
configuration is not recorded as an UNKNOWN external effect.

Translation without a `target_id`, authenticated existing-task status, and
nonproduction owned synthetic evaluations retain their documented behavior.
Production rejection applies even if a target record claims `fenced: true`,
`execution_mode: read_only` or a qualification flag. Those statements cannot
create server-side enforcement or independently establish read-only credentials.

The existing SQLite/PostgreSQL fenced destination SDKs remain bounded reference
implementations. They are not automatically wired into the HTTP transport route.
Direct developer/embedding APIs remain caller-owned interfaces; the new HTTP gate
does not sandbox a host operator or grant universal enforcement to every SDK.

## Required adapter acceptance before enabling production target execution

1. Bind authenticated agent, user/delegation context, tenant, target, exact
   parameters, allowed effects and approval to the unique operation identity.
2. Enforce that authority and a live monotonic fence atomically with the effect
   at one authoritative destination. A gateway-side check alone is insufficient.
3. Reject duplicate identities, stale/expired leaders, approval changes and
   unauthorized tenant/principal substitution under concurrent independent
   connections, process interruption, lost ACK and partition tests.
4. Preserve UNKNOWN and reservations until authoritative independently trusted
   readback resolves the exact action. Do not automatically retry ambiguous writes.
5. Qualify separately administered credentials, key enrollment/rotation/revocation,
   network/workload isolation, recovery, retention and the destination owner's
   acceptance. Internal references do not close those outside acceptance gates.

This deliberately restricts an unqualified production path. It is not production
certification. Do not use a nonproduction setting to treat a real consequential
deployment as qualified. See [handoff register](HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md)
and [security policy](../SECURITY.md).
