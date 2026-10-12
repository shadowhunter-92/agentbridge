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
