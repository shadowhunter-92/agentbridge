"""
Startup configuration validation for AgentBridge.

`validate_config()` is called once at app startup. It checks the env-var-driven
configuration for common mistakes that would otherwise surface as confusing runtime
errors: missing production secrets, malformed URLs, impossible rate-limit values, etc.

Returns a list of (severity, message) tuples. Warnings are logged; errors raise
`ConfigError` (use `fail_fast=True` to also exit). This is the "fail fast at boot"
discipline that production services need.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger("agentbridge.config")


@dataclass
class ConfigIssue:
    severity: str   # "error" | "warning"
    message: str


class ConfigError(RuntimeError):
    """Raised when one or more configuration errors make the service unsafe to start."""


def _is_prod() -> bool:
    return os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production")


def _is_postgres_url(s: str) -> bool:
    return s.startswith("postgres://") or s.startswith("postgresql://")


def validate_config(fail_fast: bool = True) -> List[ConfigIssue]:
    """Validate the environment. Returns all issues; raises if any are errors
    (unless fail_fast=False)."""
    issues: List[ConfigIssue] = []
    env = os.getenv("AGENTBRIDGE_ENV", "").lower()
    db = os.getenv("AGENTBRIDGE_DB", "")
    admin_key = os.getenv("AGENTBRIDGE_ADMIN_KEY", "")
    oidc_issuer = os.getenv("AGENTBRIDGE_OIDC_ISSUER", "")
    rate_limit = os.getenv("AGENTBRIDGE_RATE_LIMIT", "240")
    shutdown_grace = os.getenv("AGENTBRIDGE_SHUTDOWN_GRACE", "10")
    slow_log = os.getenv("AGENTBRIDGE_SLOW_LOG_SECONDS", "2.0")

    # --- errors (block startup) -------------------------------------------------

    if env in ("prod", "production"):
        if not admin_key:
            issues.append(ConfigIssue(
                "error",
                "AGENTBRIDGE_ENV=production but AGENTBRIDGE_ADMIN_KEY is not set. "
                "Without a stable admin key, operator auth rotates on every restart."
            ))
        if not db:
            issues.append(ConfigIssue(
                "error",
                "AGENTBRIDGE_ENV=production but AGENTBRIDGE_DB is not set. The in-memory "
                "store is per-process and will silently lose audit/budget/identity state "
                "on restart AND is unsafe across multiple workers."
            ))
        if db and not _is_postgres_url(db):
            # SQLite is OK for prod single-node, but warn loudly — many teams assume
            # "file on disk" means "multi-worker safe" and it does, but only for
            # certain write patterns. We've done the work to make it safe, so this
            # is a WARNING not an error.
            issues.append(ConfigIssue(
                "warning",
                f"AGENTBRIDGE_DB={db!r} is SQLite. Multi-worker is safe (atomic "
                "BEGIN IMMEDIATE), but for HA you'll want Postgres."
            ))

    if env in ("prod", "production"):
        receipt_key = os.getenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", "")
        readback_key = os.getenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", "")
        # Read-only or translation-only deployments may leave both unset;
        # reconciliation then remains fail-closed. A partially configured
        # write-capable deployment is never allowed to start.
        if bool(receipt_key) != bool(readback_key):
            issues.append(ConfigIssue(
                "error", "production reconciliation requires both destination and independent readback keys"
            ))
        for label, key in (("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", receipt_key),
                           ("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", readback_key)):
            if key and not re.fullmatch(r"[0-9a-fA-F]{64}", key):
                issues.append(ConfigIssue("error", f"{label} must be a 32-byte Ed25519 public key in hex"))
        if receipt_key and readback_key and receipt_key.lower() == readback_key.lower():
            issues.append(ConfigIssue("error", "destination and readback keys must be distinct trust roots"))
        if oidc_issuer and not oidc_issuer.startswith("https://"):
            issues.append(ConfigIssue("error", "production OIDC issuer must use HTTPS"))

    if db and _is_postgres_url(db):
        # Sanity check that psycopg is importable so we fail at boot, not first write.
        try:
            import psycopg  # noqa: F401
        except ImportError:
            issues.append(ConfigIssue(
                "error",
                "AGENTBRIDGE_DB is a postgres:// URL but psycopg is not installed. "
                "Run: pip install 'psycopg[binary]'"
            ))

    if oidc_issuer and not re.match(r"^https?://", oidc_issuer):
        issues.append(ConfigIssue(
            "error",
            f"AGENTBRIDGE_OIDC_ISSUER={oidc_issuer!r} must be an absolute URL "
            "(start with http:// or https://)."
        ))

    # Numeric envs: parse + range-check.
    try:
        rl = int(rate_limit)
        if rl <= 0 or rl > 100000:
            issues.append(ConfigIssue(
                "error", f"AGENTBRIDGE_RATE_LIMIT={rate_limit!r} must be in (0, 100000]."
            ))
    except ValueError:
        issues.append(ConfigIssue(
            "error", f"AGENTBRIDGE_RATE_LIMIT={rate_limit!r} is not an integer."
        ))

    try:
        sg = float(shutdown_grace)
        if not math.isfinite(sg) or sg < 0 or sg > 300:
            issues.append(ConfigIssue(
                "error", f"AGENTBRIDGE_SHUTDOWN_GRACE={shutdown_grace!r} must be in [0, 300]."
            ))
    except ValueError:
        issues.append(ConfigIssue(
            "error", f"AGENTBRIDGE_SHUTDOWN_GRACE={shutdown_grace!r} is not a number."
        ))

    try:
        sl = float(slow_log)
        if not math.isfinite(sl) or sl < 0:
            issues.append(ConfigIssue(
                "error", f"AGENTBRIDGE_SLOW_LOG_SECONDS={slow_log!r} must be >= 0."
            ))
    except ValueError:
        issues.append(ConfigIssue(
            "error", f"AGENTBRIDGE_SLOW_LOG_SECONDS={slow_log!r} is not a number."
        ))

    # --- warnings (logged but non-blocking) ------------------------------------

    if admin_key and len(admin_key) < 32:
        issues.append(ConfigIssue(
            "warning",
            f"AGENTBRIDGE_ADMIN_KEY is {len(admin_key)} chars; recommend >= 32 chars "
            "(use `openssl rand -hex 32`)."
        ))

    if oidc_issuer and not (os.getenv("AGENTBRIDGE_OIDC_PUBLIC_KEY_PEM")
                            or os.getenv("AGENTBRIDGE_OIDC_PUBLIC_KEY_FILE")
                            or os.getenv("AGENTBRIDGE_OIDC_JWKS_URL")):
        # Discovery will be attempted at first use; that's fine but mention it.
        issues.append(ConfigIssue(
            "warning",
            "OIDC issuer is set but no signing key configured. JWKS auto-discovery will "
            "be used (first request will incur a fetch)."
        ))

    # --- log + maybe raise ------------------------------------------------------

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    for w in warnings:
        logger.warning("config: %s", w.message)
    for e in errors:
        logger.error("config: %s", e.message)

    if errors and fail_fast:
        raise ConfigError(f"{len(errors)} configuration error(s); see logs above")

    return issues
