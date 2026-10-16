"""Fail-closed boundary between legacy single-tenant and enrolled tenant modes."""

import os

from .config import ConfigError


def authority_mode():
    mode = os.getenv("AGENTBRIDGE_AUTHORITY_MODE", "legacy_single_tenant")
    if mode not in ("legacy_single_tenant", "multi_tenant"):
        raise ConfigError("unknown authority mode; explicit supported mode required")
    return mode


def require_legacy_authority():
    if authority_mode() != "legacy_single_tenant":
        raise ConfigError("legacy entry point cannot serve multi_tenant authority; use the enrolled tenant facade")
