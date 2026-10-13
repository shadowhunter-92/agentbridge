"""Non-executable task lifecycle safety contract, without network transports."""
from dataclasses import replace
import pytest

from src.protocols.task_lifecycle import TaskLifecycle, TaskState, LifecycleRejected


def initial():
    return TaskLifecycle("task-123", "context-123", "a2a")


def test_valid_stream_of_lifecycle_states_cannot_replay():
    task = initial()
    task = task.transition(TaskState.WORKING, sequence=1)
    task = task.transition(TaskState.INPUT_REQUIRED, sequence=2)
    task = task.transition(TaskState.WORKING, sequence=3)
    done = task.transition(TaskState.COMPLETED, sequence=4)
    assert done.terminal
    assert task.state == TaskState.WORKING
    assert done.sequence == 4
    with pytest.raises(LifecycleRejected, match="illegal or terminal"):
        done.transition(TaskState.WORKING, sequence=5)


@pytest.mark.parametrize("sequence", [-1, 0, True, 0.5])
def test_non_increasing_invalid_sequence_denied(sequence):
    with pytest.raises(LifecycleRejected):
        initial().transition(TaskState.WORKING, sequence=sequence)


@pytest.mark.parametrize("state", ["unknown", "completed", None, 12, True])
def test_unknown_and_untyped_state_denied(state):
    with pytest.raises(LifecycleRejected):
        initial().transition(state, sequence=1)


@pytest.mark.parametrize("state", list(TaskState))
def test_terminal_states_cannot_create_new_work(state):
    if state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED, TaskState.REJECTED):
        t = replace(initial(), state=state, sequence=3)
        with pytest.raises(LifecycleRejected):
            t.transition(TaskState.WORKING, sequence=4)


def test_submitted_cannot_directly_complete_without_work_transition():
    with pytest.raises(LifecycleRejected):
        initial().transition(TaskState.COMPLETED, sequence=1)


def test_a2a_snapshot_is_metadata_not_new_dispatch():
    task = TaskLifecycle.from_a2a_task({"kind":"task","id":"id-1","contextId":"ctx-1",
                                        "status":{"state":"working"},
                                        "metadata":{"agentbridge_sequence":11},
                                        "history":[{"parts":[{"kind":"data","data":{"name":"delete_all"}}]}]})
    assert task.state == TaskState.WORKING
    assert task.sequence == 11
    assert not hasattr(task, "capability")


@pytest.mark.parametrize("invalid", [
    {"kind":"message","id":"task","contextId":"c","status":{"state":"submitted"}},
    {"kind":"task","id":"task","contextId":"c","status":{"state":"unknown"}},
    {"kind":"task","id":"task","contextId":"c","status":{"state":None}},
    {"kind":"task","id":"task","contextId":"c","status":"working"},
    {"kind":"task","id":"task","contextId":None,"status":{"state":"working"}},
])
def test_invalid_task_snapshot_denied(invalid):
    with pytest.raises(LifecycleRejected):
        TaskLifecycle.from_a2a_task(invalid)
