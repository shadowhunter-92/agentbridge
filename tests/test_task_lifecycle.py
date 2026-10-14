"""A2A lifecycle snapshots are never executable canonical tool actions."""
import pytest
from src.protocols.task_lifecycle import TaskLifecycle, TaskState, LifecycleRejected


def task(state="working", **extras):
    return {"kind": "task", "id": "task-1", "contextId": "ctx-1",
            "status": {"state": state}, **extras}


def test_parse_snapshot_and_no_network_side_effect():
    snap = TaskLifecycle.from_a2a_task(task("working", metadata={"agentbridge_sequence": 3}))
    assert (snap.task_id, snap.context_id, snap.sequence, snap.state) == (
        "task-1", "ctx-1", 3, TaskState.WORKING)
    assert not snap.terminal


@pytest.mark.parametrize("state", ["completed", "failed", "canceled", "rejected"])
def test_terminal_snapshots(state):
    assert TaskLifecycle.from_a2a_task(task(state)).terminal


def test_legal_sequence_and_terminal_no_resurrection():
    current = TaskLifecycle(task_id="t", context_id="c", source_protocol="a2a")
    current = current.transition(TaskState.WORKING, sequence=1)
    current = current.transition(TaskState.COMPLETED, sequence=2)
    assert current.terminal
    for state, seq in ((TaskState.WORKING, 3), (TaskState.COMPLETED, 3)):
        with pytest.raises(LifecycleRejected):
            current.transition(state, sequence=seq)


def test_immediate_completion_rejected_until_working():
    t = TaskLifecycle("t", "c", "a2a")
    with pytest.raises(LifecycleRejected):
        t.transition(TaskState.COMPLETED, sequence=1)
    assert t.transition(TaskState.WORKING, sequence=1).transition(
        TaskState.COMPLETED, sequence=2
    ).terminal


@pytest.mark.parametrize("seq", [0, -1, 1, True, 1.5, "2"])
def test_stale_or_invalid_sequence_denied(seq):
    t = TaskLifecycle("t", "c", "a2a", state=TaskState.WORKING, sequence=1)
    with pytest.raises(LifecycleRejected):
        t.transition(TaskState.COMPLETED, sequence=seq)


@pytest.mark.parametrize("bad", [
    {"kind": "message"},
    {"kind": "task", "id": "t", "contextId": "c", "status": {"state": "unknown"}},
    {"kind": "task", "id": "t", "contextId": "c", "status": "completed"},
    {"kind": "task", "id": "t", "contextId": "c", "status": {"state": "working"}, "metadata": "bad"},
    {"kind": "task", "id": "t", "contextId": "c", "status": {"state": "working"}, "metadata": []},
    {"kind": "task", "id": "t", "contextId": "c", "status": {"state": "working"}, "metadata": False},
    {"kind": "task", "id": "t", "contextId": "c", "status": {"state": "working"}, "metadata": {"agentbridge_sequence": True}},
    {"kind": "task", "id": " ", "contextId": "c", "status": {"state": "working"}},
    {"kind": "task", "id": "t", "contextId": " ", "status": {"state": "working"}},
])
def test_malformed_snapshots_denied(bad):
    with pytest.raises(LifecycleRejected):
        TaskLifecycle.from_a2a_task(bad)


def test_identity_and_source_are_immutable():
    from dataclasses import FrozenInstanceError
    t = TaskLifecycle("t", "c", "a2a")
    with pytest.raises(FrozenInstanceError):
        t.task_id = "another"


def test_other_protocol_must_not_assume_a2a_lifecycle():
    with pytest.raises(LifecycleRejected):
        TaskLifecycle("t", "c", "mcp")
