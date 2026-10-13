"""A2A lifecycle/control messages cannot become unintended agent actions."""
import pytest
from src.protocols.a2a import A2aAdapter


@pytest.mark.parametrize("state",[
    "completed","failed","canceled","rejected","working","input-required",
    "auth-required","unknown-state",
])
def test_a2a_non_submitted_tasks_not_new_executable_actions(state):
    wire={"kind":"task","id":"task-1","status":{"state":state},
          "history":[{"kind":"message","parts":[
              {"kind":"data","data":{"name":"delete-all","arguments":{}}}]}]}
    with pytest.raises(ValueError,match="lifecycle state"):
        A2aAdapter().to_canonical_call(wire)


@pytest.mark.parametrize("method",["tasks/cancel","tasks/resubscribe","tasks/get"])
def test_a2a_control_methods_denied(method):
    wire={"jsonrpc":"2.0","id":1,"method":method,
          "params":{"task":{"kind":"task","status":{"state":"submitted"},"history":[]}}}
    with pytest.raises(ValueError,match="lifecycle methods"):
        A2aAdapter().to_canonical_call(wire)


@pytest.mark.parametrize("method", ["tasks/sendSubscribe", "message/send", "message/stream", "tasks/pushNotificationConfig/set", "unknown/execute", "notifications/taskStatus"])
def test_unrecognized_a2a_methods_fail_closed(method):
    wire = {"jsonrpc": "2.0", "id": "t-1", "method": method, "params": {"task": {
        "kind": "task", "status": {"state": "submitted"}, "history": [
            {"parts": [{"kind": "data", "data": {"name": "destructive_tool", "arguments": {}}}]}
        ]
    }}}
    with pytest.raises(ValueError, match="unsupported A2A method"):
        A2aAdapter().to_canonical_call(wire)


@pytest.mark.parametrize("status", ["working", "completed", 1, [], None])
def test_malformed_task_status_cannot_hide_lifecycle(status):
    wire = {"kind": "task", "status": status, "history": [
        {"parts": [{"kind": "data", "data": {"name": "destructive_tool", "arguments": {}}}]}
    ]}
    with pytest.raises(ValueError, match="lifecycle status"):
        A2aAdapter().to_canonical_call(wire)
