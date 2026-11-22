"""Dependency-level regressions; these do not establish an AgentBridge exploit.

Keep the upstream fixed validation contracts and first-party strict bodies intact
when updating the runtime lock. No target or consequential action is executed.
"""

from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, with_config
from pydantic.dataclasses import dataclass
from typing_extensions import TypedDict

from src.api.tenant_control_plane import RouteBody
from src.governance.task_intents import TaskSubmission


class TypedExtras(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[Annotated[str, Field(pattern=r"^x_")], int]


@with_config(ConfigDict(extra="allow"))
class AliasedMapping(TypedDict):
    count: Annotated[int, Field(alias="external_count")]


@dataclass(config=ConfigDict(extra="allow"))
class AliasedRecord:
    count: int = Field(alias="external_count")


def test_json_extra_keys_follow_the_declared_key_type():
    assert TypedExtras.model_validate_json('{"x_count": 3}').model_extra == {"x_count": 3}
    with pytest.raises(ValidationError):
        TypedExtras.model_validate_json('{"count": 3}')


@pytest.mark.parametrize("schema", [AliasedMapping, AliasedRecord])
def test_extra_field_name_cannot_overwrite_validated_alias(schema):
    adapter = TypeAdapter(schema)
    clean = adapter.validate_python({"external_count": 7})
    conflicting = adapter.validate_python({"external_count": 7, "count": "unvalidated"})
    if isinstance(conflicting, dict):
        assert clean["count"] == conflicting["count"] == 7
        assert type(conflicting["count"]) is int
    else:
        assert clean.count == conflicting.count == 7
        assert type(conflicting.count) is int
    with pytest.raises(ValidationError):
        adapter.validate_python({"external_count": "invalid"})


@pytest.mark.parametrize("model", [RouteBody, TaskSubmission])
def test_governed_request_bodies_keep_strict_types_and_reject_extras(model):
    body = {
        "request_scope": "route" if model is RouteBody else "task.submit",
        "src": "mcp",
        "dst": "mcp",
        "wire": {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
        "operation_id": "dependency-check-operation",
        "target_id": "synthetic",
    }
    if model is TaskSubmission:
        body.update(task_id="synthetic-task", context_id="synthetic-context")
    assert model.model_validate(body).src == "mcp"
    for changes in ({"src": 1}, {"owner_id": "untrusted"}, {"cost": 0}, {"tenant_id": "other"}):
        with pytest.raises(ValidationError):
            model.model_validate({**body, **changes})
