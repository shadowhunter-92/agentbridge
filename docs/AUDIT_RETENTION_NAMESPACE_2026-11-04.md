# Audit retention namespace boundary — November 4–5, 2026

**PARTIALLY TESTED; production NO-GO.** This local working unit starts from
`35f37222597341d2c23e9cd9d0baddf1e36f99f7` on
`fix/retention-authority-2026-11-04`. New-source hosted CI is **NOT STARTED**.
Baseline CI run `41638001805` does not cover this patch. No merge, release,
deployment, external destination acceptance or production retention is claimed.

## Existing behavior and reproduced gap

The existing nonproduction store retention API preserves the current audit
head and refuses deletion for durable holds, any retained operation or task
operation link, nonterminal tasks and pending budget reservations. Audit
capacity triggers account retained rows and UTF-8 payload bytes in the same
transaction. These controls do not bound physical database pages, indexes,
WAL, backups or fleet storage.

The API used unqualified SQL names for hold/reference checks and audit
deletion. A trusted embedding could introduce a same-connection TEMP table
or view that hid a durable object. An empty TEMP `audit_holds`, for example,
hid an enabled durable hold and allowed the governed API to delete an audit
prefix. Empty TEMP operation, budget and lifecycle objects reproduced the
same failure while their durable UNKNOWN, reservation or nonterminal task
rows remained. This is a local SQL embedding integrity defect; it does not
make privileged raw SQL deletion an authorized retention path.

The first TEMP-only correction left a related SQLite durable-main alias gap.
A preexisting `Audit_Holds` table accepted real hold API writes, but the
retention catalog lookup compared its name case-sensitively and missed it.
Preexisting upper/mixed-case aliases reproduced the gap for all six retention
names. The follow-up refuses these noncanonical durable names before deletion;
it preserves the original tables and values without automatic repair.

## Bounded correction

The existing `checkpoint_capacity.assert_sqlite_namespace` and
`assert_postgres_namespace` helpers now accept a keyword-only trusted
`additional_reserved` tuple. Their existing defaults remain unchanged. Catalog
name values remain bound SQL parameters. The retention guard passes its
existing four reference-table names, adding them to the helpers' existing
reserved audit, hold, checkpoint and tenant-binding names.

The existing durable-hold checks move into the existing retention guard,
immediately after the reused namespace check and before reference reads.
SQLite rejects TEMP aliases using its ASCII identifier case folding; both
TEMP tables and views are covered. PostgreSQL rejects matching TEMP relation
names. Quoted PostgreSQL identifiers with a different case are different names
and do not mask these unquoted durable identifiers.

For the additional trusted names, the reused SQLite helper also applies its
existing canonical-main catalog check. Retention supplies all six critical
names. Default checkpoint callers retain their existing two-table canonical
check and original error contract.

SQLite retains the same `sql_atomic` transaction. PostgreSQL retains the same
order: hold lock `911003`, namespace/hold checks, reference-table SHARE locks,
then audit lock `911001` before head selection and deletion. Production
refusal still occurs before this work. No policy, schema version, database
routine, capacity limit, outcome, approval or replay rule changes.

Saturation and namespace denial preserve existing evidence. The correction
does not evict history, expire UNKNOWN, refund reservations, retry uncertain
actions or create a new authority implementation.

## Local evidence

The first sandbox pytest invocation encountered Windows temporary-directory
ACL failures: 39 setup errors and no product cases executed. Its JUnit and
runner record are retained separately. The authorized native test fallback
then produced these source-bound observations:

| Observation | Result |
| --- | --- |
| SQLite baseline reproduction, before runtime changes | 37 failed, 2 passed; zero skips/errors |
| PostgreSQL baseline reproduction, exact baseline runtime bytes | 12 failed; zero skips/errors |
| Durable-main alias reproduction, TEMP-only patch | 12 failed; zero passes/skips/errors |
| Final explicitly selected SQLite regression group | 241 passed, 9 backend-specific skips; zero failures/errors |
| Final explicitly selected schema-only PostgreSQL group | 98 passed; zero skips/failures/errors |

The PostgreSQL baseline run temporarily used only the three baseline runtime
files, then restored the patched bytes exactly. Tests used the explicitly
qualified, owned local PostgreSQL 16 service, fixed to loopback and a disposable
test database. The existing fixture created and cleaned only UUID-named schemas.
No cloud service was used. A separate initial runner configuration-shape error
executed no product tests and is not counted as RED evidence.

An earlier, broader completed run is preserved as 350 passes, 69 skips and
seven failures. Its selected preexisting migration fixture exceeded the local
schema-only handoff: it created disposable UUID restore databases and invoked
temporary Docker clients, whose `pg_dump` could not reach server loopback.
The run completed before a targeted stop check; it is not an interrupted run
or a successful restore qualification. JUnit recorded no teardown errors.
The one remaining restore database had directory modification/change times
on October 16, predating this November run, and no sessions; it was left
untouched. Logs that rendered the disposable test password were redacted,
with original/redacted hashes retained. The final PostgreSQL selection omits
every role/global-TEMP and restore-database fixture and saves exact node IDs.

The new matrix covers six names: `audit`, `audit_holds`, `agent_operations`,
`task_operation_links_v1`, `budgets`, and `task_lifecycle_snapshots`. SQLite
covers lower/upper/mixed-case TEMP tables and views. PostgreSQL covers TEMP
tables and views with names that actually mask the unquoted durable names.
The standalone link test uses an existence-predicate sentinel, not a claimed
admission receipt. A separate real queued-admission SQLite test checks the exact
durable snapshot, UNKNOWN state, reservation token, legal hold and task state.
The PostgreSQL tenant-role equivalent is skipped because that fixture forbids
TEMP privileges; the separate privileged-embedding PostgreSQL matrix tests
the library guard. Existing checkpoint tests exercise unchanged helper defaults.

Local JUnit XML, runner metadata, tested-source SHA256 manifests and saved
runtime/test bytes are retained under the ignored
`outputs/retention-authority-2026-11-04/` directory. These local observations
are **PARTIALLY TESTED**, not hosted CI or controlled-staging acceptance.
The local environment lacks the pytest timeout plugin and reported its two
unknown-configuration warnings; the evidence runner separately bounded each
pytest subprocess. The new CI step runs the complete new test module after
the existing PostgreSQL recovery evidence upload, without changing previous
test selections. That workflow has not run on this source.

## Remaining limits

Reference-indexed hold-safe retention, independent checkpoint/custody
acceptance, physical storage quotas, long-history performance and mixed-version
operation remain open. A database operator who can alter durable tables,
triggers or policy remains outside this local integrity boundary. Raw SQL
deletion still bypasses the governed store retention authorization checks.
Operators must stop/drain old retention workers and use the current API.
Production audit deletion remains forbidden. The isolated P35 replay-capacity
candidate remains BLOCKED and untouched.
