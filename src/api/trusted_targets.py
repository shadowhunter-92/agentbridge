"""Security boundary for operator-owned agent targets and route cost reservations.

The caller can choose a *named* target only. The executable, URL and per-target
capability allowlist are owned by the deployment administrator.
"""
from __future__ import annotations

import json
import math
import ipaddress
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse


class SecurityConfigurationError(ValueError):
    """Invalid operator policy or unauthorized route configuration."""


@dataclass(frozen=True)
class TrustedTarget:
    target_id: str
    protocol: str
    capability: str
    invocation: dict[str, Any]


def _object(value: str | None, label: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise SecurityConfigurationError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SecurityConfigurationError(f"{label} must be a JSON object")
    return parsed


def validate_cost(value: Any) -> float:
    if isinstance(value, bool):
        raise SecurityConfigurationError("cost cannot be boolean")
    try:
        result = float(value)
    except (ValueError, OverflowError, TypeError) as exc:
        raise SecurityConfigurationError("cost must be a finite, nonnegative number") from exc
    if not math.isfinite(result) or result < 0:
        raise SecurityConfigurationError("cost must be a finite, nonnegative number")
    return result


def effective_call_cost(value: Any, capability: str,
                        *, env: Mapping[str, str] | None = None) -> float:
    """Production reserve amounts are operator-defined; not actual metered usage.

    A fixed reservation is NOT an accurate billing measurement. Any variable final
    charge must be reconciled from independently trusted usage records.
    """
    env = os.environ if env is None else env
    requested = validate_cost(value)
    if env.get("AGENTBRIDGE_ENV", "").lower() not in ("prod", "production"):
        return requested
    schedule = _object(env.get("AGENTBRIDGE_COST_SCHEDULE_JSON"),
                       "AGENTBRIDGE_COST_SCHEDULE_JSON")
    if capability not in schedule:
        raise SecurityConfigurationError("production cost policy missing for capability")
    return validate_cost(schedule[capability])


def resolve_target(target_id: Any, protocol: str, capability: str,
                   *, env: Mapping[str, str] | None = None,
                   agent_id: str | None = None) -> dict[str, Any] | None:
    """Resolve an agent-selected target ID to an administrator-configured route.

    Configure AGENTBRIDGE_TARGETS_JSON with an object keyed by target ID.
    Never accept an agent-supplied executable, URL, argv or endpoint directly.
    Missing target_id allows translation-only operation (no execution).
    """
    env = os.environ if env is None else env
    if target_id is None:
        return None
    if not isinstance(target_id, str) or not target_id.strip():
        raise SecurityConfigurationError("target_id must be a nonempty string")
    record = _object(env.get("AGENTBRIDGE_TARGETS_JSON"),
                     "AGENTBRIDGE_TARGETS_JSON").get(target_id)
    if not isinstance(record, dict):
        raise SecurityConfigurationError("target_id not registered by operator")
    if record.get("protocol") != protocol:
        raise SecurityConfigurationError("destination protocol mismatch")
    capabilities = record.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities or not all(
            isinstance(x, str) and bool(x) for x in capabilities):
        raise SecurityConfigurationError("target requires a nonempty capability allowlist")
    if capability not in capabilities:
        raise SecurityConfigurationError("capability not authorized for target")
    if env.get("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
        # Binding trust to destination *and* agent avoids any registered agent
        # inheriting permissions for every configured target.
        allowed_agents = record.get("allowed_agents")
        if not isinstance(allowed_agents, list) or not allowed_agents or not all(
                isinstance(x, str) and bool(x) for x in allowed_agents):
            raise SecurityConfigurationError("production target requires allowed_agents")
        if not agent_id or agent_id not in allowed_agents:
            raise SecurityConfigurationError("agent not authorized for target")
    kind = record.get("kind")
    if (protocol, kind) not in {
            ("mcp", "mcp_stdio"), ("a2a", "a2a_http"), ("acp", "acp_http")}:
        raise SecurityConfigurationError("unsupported target protocol/transport pair")
    if kind == "mcp_stdio":
        command, args = record.get("command"), record.get("args", [])
        if not isinstance(command, str) or not command.strip() or not isinstance(args, list) or not all(
                isinstance(arg, str) for arg in args):
            raise SecurityConfigurationError("invalid administrator-defined executable or arguments")
        return {"kind": kind, "command": command, "args": list(args)}

    address = record.get("base_url")
    if not isinstance(address, str):
        raise SecurityConfigurationError("target HTTP URL missing")
    u = urlparse(address)
    if (u.scheme not in ("http", "https") or not u.hostname
            or u.username is not None or u.password is not None or u.fragment):
        raise SecurityConfigurationError("target must be an absolute HTTP(S) URL without userinfo/fragment")
    if env.get("AGENTBRIDGE_ENV", "").lower() in ("prod", "production") and u.scheme != "https":
        raise SecurityConfigurationError("production target must use HTTPS")
    if env.get("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
        # URL allowlisting alone is not a DNS-rebinding defense. Require a
        # separate reviewed network egress proxy for live HTTP targets.
        # Fail closed unless the operator affirmatively configures isolation.
        if env.get("AGENTBRIDGE_EGRESS_PROXY_ENFORCED") != "1":
            raise SecurityConfigurationError("production HTTP execution requires enforced egress proxy")
        try:
            if ipaddress.ip_address(u.hostname):
                raise SecurityConfigurationError("literal IP target prohibited")
        except ValueError:
            pass
        host = u.hostname.lower().rstrip(".")
        if host in ("localhost", "localhost.localdomain") or "." not in host or host.endswith((".local",".internal",".test")):
            raise SecurityConfigurationError("private or ambiguous DNS target prohibited")
    invocation: dict[str, Any] = {"kind": kind, "base_url": address}
    if kind == "acp_http":
        name = record.get("agent_name", "agent")
        if not isinstance(name, str) or not name:
            raise SecurityConfigurationError("invalid agent_name")
        invocation["agent_name"] = name
    return invocation
