# Durable task-status SDK

`src.protocols.durable_task_lifecycle.DurableTaskLifecycle` extends the non-executable
state model with SQLite/PostgreSQL snapshots and event history. It is a library
component. The separate opt-in [A2A status observer](A2A_STATUS_STREAMING.md)
projects its existing tasks over authenticated HTTP/SSE.

```python
from src.governance.store import SqliteStore
from src.protocols.task_lifecycle import TaskLifecycle, TaskState
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle

store = SqliteStore("synthetic-tasks.sqlite")
tasks = DurableTaskLifecycle(store, max_active_per_owner=16, max_events_per_task=128)
tasks.create("authenticated-owner", TaskLifecycle("task-1", "context-1", "a2a"))
tasks.transition("authenticated-owner", "task-1", TaskState.WORKING, expected_sequence=0)
tasks.cancel("authenticated-owner", "task-1", expected_sequence=1)
assert tasks.get("authenticated-owner", "task-1").terminal
store.close()
```

The embedding service must authenticate and authorize the owner before calling
this SDK. Never derive the owner from untrusted task metadata. The same task ID
can exist for different owners, and an owner cannot read/update another scope.
Stale compare-and-update sequences and terminal resurrection are rejected.
Replicas must use identical capacity settings.

`events(after_sequence=..., limit=...)` returns at most 100 events. Reconnect using
the last event actually consumed. `watch(...)` is a pull-based async iterator with
one bounded page, no background queue and a bounded poll interval. Disconnecting
or canceling an iterator does not alter the task. A final event slot is reserved
so a saturated task can terminate and release active-task admission.

Cancellation and resumption change status only. They never retry an operation,
refund reserved budget, undo a committed action or authorize a new tool call.
Keep action outcomes in the operation ledger and reconcile uncertain effects
through the Trust/Evidence path.

Retention quotas for total historical tasks, independent tamper evidence,
fleet-wide network quotas, full A2A resumability and production service
backpressure remain separate work. The observer supplies only the documented
owner/task-bound replay extension and process-level stream bounds. This SDK does not certify those guarantees.

Run `python -m pytest tests/test_durable_task_lifecycle.py -q` with an explicit
disposable `AGENTBRIDGE_TEST_PG` to exercise both SQL backends.
