# Signing-policy coordination with tenant authority

Authority and tenant signing stores may use separate connections and schemas
within one PostgreSQL database. The previous journal's exclusive advisory key
911005 conflicted with an authority read guard holding that same key on another
connection. Both publication and settlement key reads could wait on the caller's
own authority transaction.

New PostgreSQL journal operations retain911005 as a shared compatibility barrier
against older journal workers, which take it exclusively. A private singleton
coordination row now supplies writer/read exclusion: publication takes FOR UPDATE;
settlement and SDK verification take FOR SHARE. Thus an authority read guard can
remain held, while rotations still wait for settlement commit. Existing signed
history, controller pins, revision floors and rotation validation are unchanged.

Bootstrap takes the compatibility barrier before the existing911004 schema lock.
It creates the coordination row only when the coordination table is first
introduced, including for an existing journal. A missing row or unsupported
version in an existing table fails closed. SQLite retains its existing immediate
transaction writer exclusion. New signing tables in a bound tenant store receive
the existing namespace write guards within bootstrap, before return.

settlement_keys requires a cursor from its own store and an active transaction;
autocommit or another connection cannot silently discard the locking contract.
The standalone Evidence SDK requests a read transaction for policy verification.

Qualification reproduces two PostgreSQL lock timeouts and two legacy-write
guard failures before the change. The corrected group covers actual database
blocking edges against an old exclusive worker and a current settlement reader,
damaged metadata, active/same-store cursor negatives, and existing signed-history,
rotation, rollback and reconciliation tests. Local current regression:66 passed,
five expected PostgreSQL-only SQLite skips. Hosted exact-head CI is separate.

This is a coordination primitive, not a complete tenant evidence HTTP/background
service or independent custody acceptance. Cross-connection journal operations
compose with authority read guards. Combining enrollment mutation and journal
mutation inside an exclusive authority write guard is unsupported; no atomic
cross-store enrollment/key-policy transaction is claimed. Provisioning, external
revision floors, destination/readback control and production qualification remain
operator obligations. Engineering alpha and production NO-GO remain.
