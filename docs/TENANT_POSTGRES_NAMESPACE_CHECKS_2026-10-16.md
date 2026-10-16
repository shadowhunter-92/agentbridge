# Configured PostgreSQL namespace checks

Tenant registry startup checks configured tenant and authority schema names
against each tenant connection's actual PostgreSQL catalog. It must not skip
those checks because the connections report different addresses, ports or
database names: proxies, aliases and multi-homed servers can report differently.
An actual USAGE grant into another configured protected schema rejects startup.
The current connection's own schema name is excluded from this name check;
separate databases may legitimately reuse that name. Existing physical/store
identity and durable tenant-binding checks remain in force.

This is a conservative configured-name check, not discovery of all schemas,
network topology proof or an isolation guarantee against a database owner.
Operators still provision dedicated direct-login roles with no elevated,
inherited, database-owner or TEMP privileges, and private search paths. Changing
SQL privileges after startup requires renewed provisioning review and restart;
this change does not install a privilege-change monitor.

The regression uses actual PostgreSQL USAGE/SELECT grants and verifies a direct
cross-schema sentinel read before asserting registry rejection. Only the reported
endpoint metadata is changed to exercise the former skip; no claim of a real
multi-address network deployment is made. Removing those grants must restore
normal registry construction. Both tenant and authority targets are covered.
SQLite skips these PostgreSQL-only cases. Tests do not touch outside systems.

Targeted results before the correction: two PostgreSQL failures. After: two
passes, two expected SQLite skips. Storage/runtime regression:33 passed, three
expected PostgreSQL-only SQLite skips. Hosted CI and wider qualification are
separate evidence; this document alone does not establish their acceptance.
Engineering alpha and production NO-GO restrictions remain.
