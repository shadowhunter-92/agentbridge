"""Explicit, non-executable agent task lifecycle contract.

This model is intentionally separate from CanonicalCall. A long-running task,
status update, cancellation, resumption or push notification MUST NOT be
converted into a new capability execution solely by appearing on a transport.

No network, persistence, automatic retries or streaming transports are shipped
by this module. It is a bounded contract for future protocol integration.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    AUTH_REQUIRED = "auth-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    REJECTED = "rejected"


_TERMINAL = frozenset((TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED, TaskState.REJECTED))
_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.SUBMITTED: frozenset((TaskState.WORKING, TaskState.INPUT_REQUIRED,
                                  TaskState.AUTH_REQUIRED, TaskState.FAILED,
                                  TaskState.CANCELED, TaskState.REJECTED)),
    TaskState.WORKING: frozenset((TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED,
                                TaskState.COMPLETED, TaskState.FAILED,
                                TaskState.CANCELED, TaskState.REJECTED)),
    TaskState.INPUT_REQUIRED: frozenset((TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED)),
    TaskState.AUTH_REQUIRED: frozenset((TaskState.WORKING, TaskState.CANCELED,
                                      TaskState.REJECTED, TaskState.FAILED)),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELED: frozenset(),
    TaskState.REJECTED: frozenset(),
}


class LifecycleRejected(ValueError):
    """Invalid lifecycle update, replay, state transition or missing identity."""


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 128) or value.strip() != value:
        raise LifecycleRejected(f"{label} must be a bounded nonempty identifier")
    return value


@dataclass(frozen=True, slots=True)
class TaskLifecycle:
    task_id: str
    context_id: str
    source_protocol: str
    state: TaskState = TaskState.SUBMITTED
    sequence: int = 0

    def __post_init__(self) -> None:
        _identifier(self.task_id, "task_id")
        _identifier(self.context_id, "context_id")
        _identifier(self.source_protocol, "source_protocol")
        if self.source_protocol != "a2a":
            raise LifecycleRejected("only the reviewed A2A task subset has a lifecycle adapter")
        if not isinstance(self.state, TaskState) or type(self.sequence) is not int or self.sequence < 0:
            raise LifecycleRejected("invalid lifecycle state or sequence")

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL

    def transition(self, new_state: TaskState, *, sequence: int) -> TaskLifecycle:
        """Return a new state after strictly increasing event sequence and legal transition.

        This does not automatically execute, retry or cancel any external effect.
        Callers must persist/check sequence atomically in their own durable store.
        """
        if not isinstance(new_state, TaskState):
            raise LifecycleRejected("unknown or unreviewed task state")
        if type(sequence) is not int or sequence <= self.sequence:
            raise LifecycleRejected("stale or replayed lifecycle event sequence")
        if new_state not in _TRANSITIONS[self.state]:
            raise LifecycleRejected("illegal or terminal task lifecycle transition")
        return replace(self, state=new_state, sequence=sequence)

    @classmethod
    def from_a2a_task(cls, task: Mapping[str, Any]) -> TaskLifecycle:
        """Parse a task state snapshot, never an executable tool action."""
        if not isinstance(task, Mapping) or task.get("kind") != "task":
            raise LifecycleRejected("A2A lifecycle requires a task object")
        raw = task.get("status")
        if not isinstance(raw, Mapping) or not isinstance(raw.get("state"), str):
            raise LifecycleRejected("A2A task state is required")
        try:
            state = TaskState(raw["state"])
        except ValueError as exc:
            raise LifecycleRejected("unknown A2A task state") from exc
        metadata = task.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise LifecycleRejected("task metadata must be an object")
        seq = metadata.get("agentbridge_sequence", 0)
        return cls(
            task_id=task.get("id"), context_id=task.get("contextId"),
            source_protocol="a2a", state=state, sequence=seq,
        )
