"""Offline operator wrapper for the existing explicit tenant migration API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from contextlib import ExitStack
from pathlib import Path

from ..api.auth_oidc import OidcConfig, OidcVerifier
from .authority import AuthorityDirectory
from .store import PostgresStore, SqliteStore
from .tenant_migration import TenantMigration


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration member")
        result[key] = value
    return result


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError("invalid explicit operator configuration")


def _store(config, stack):
    if not isinstance(config, dict):
        raise ValueError("explicit SQL backend required")
    if config.get("backend") == "sqlite":
        _keys(config, ("backend", "path"))
        if not isinstance(config["path"], str) or not Path(config["path"]).is_file():
            raise ValueError("existing SQLite file required")
        store = SqliteStore(config["path"])
    elif config.get("backend") == "postgres":
        _keys(config, ("backend", "dsn"))
        if not isinstance(config["dsn"], str) or not 1 <= len(config["dsn"]) <= 8192:
            raise ValueError("explicit bounded PostgreSQL connection required")
        store = PostgresStore(config["dsn"])
    else:
        raise ValueError("unsupported SQL backend")
    stack.callback(store.close)
    return store


def execute(config, action, *, tenant_id=None, archive=None):
    """Trusted local operator configuration; never an HTTP request body.

    A fresh JWT is obtained out of band and read from an environment variable.
    Only pinned public-key verification is supported by this offline tool.
    Backups and separate restores must already exist; no cloud provisioning,
    shell commands, database dropping or implicit historical assignment occurs.
    """
    _keys(config, ("authority", "source", "operator_issuer"), ("restored",))
    _keys(config["authority"], ("store", "audience", "public_key_pem"))
    if action not in ("freeze", "verify-backup", "activate", "rollback", "status"):
        raise ValueError("unsupported migration action")
    for field in ("audience", "public_key_pem"):
        value = config["authority"][field]
        if not isinstance(value, str) or not 1 <= len(value) <= 32768:
            raise ValueError("explicit offline issuer verification required")
    token = os.environ.get("AGENTBRIDGE_OPERATOR_TOKEN", "")
    if not token or len(token) > 65536:
        raise ValueError("fresh operator JWT required")
    with ExitStack() as stack:
        authority = config["authority"]
        verifier = OidcVerifier(
            OidcConfig(
                issuer=config["operator_issuer"],
                audience=authority["audience"],
                public_key_pem=authority["public_key_pem"],
            )
        )
        directory = AuthorityDirectory(
            _store(authority["store"], stack), verifiers={config["operator_issuer"]: verifier}
        )
        actor = directory.authenticate_operator(config["operator_issuer"], token)
        migration = TenantMigration(directory, _store(config["source"], stack))
        if action == "status":
            return migration.status(actor)
        if action == "freeze":
            return migration.freeze(actor, tenant_id)
        if action == "rollback":
            return migration.rollback(actor)
        if "restored" not in config or archive is None:
            raise ValueError("independent restore and backup archive required")
        restored = _store(config["restored"], stack)
        if action == "verify-backup":
            return migration.verify_backup(actor, restored, archive)
        return migration.activate(actor, restored, archive)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit offline AgentBridge tenant assignment and safe rollback")
    parser.add_argument("--config", required=True, help="private trusted operator JSON configuration")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("freeze").add_argument("--tenant", required=True)
    for action in ("verify-backup", "activate"):
        sub.add_parser(action).add_argument("--archive", required=True)
    sub.add_parser("rollback")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    try:
        with Path(args.config).open("rb") as source:
            content = source.read(65537)
        if len(content) > 65536:
            raise ValueError("operator configuration exceeds size limit")
        config = json.loads(content, object_pairs_hook=_unique)
        result = execute(
            config, args.action, tenant_id=getattr(args, "tenant", None), archive=getattr(args, "archive", None)
        )
    except Exception:
        # DSNs and tokens may be present in low-level connection exceptions.
        # Keep diagnostic detail in trusted operator tooling, never stdout logs.
        print(json.dumps({"status": "denied", "error": "migration preconditions or operator authorization failed"}))
        return 1
    if "manifest" in result:
        # Report hashes/counts rather than historical DDL defaults or topology.
        manifest = result["manifest"]
        result = {key: result[key] for key in ("migration_id", "tenant_id", "phase", "backup_sha256")}
        result["historical_tables"] = len(manifest["tables"])
        result["historical_rows"] = sum(table["rows"] for table in manifest["tables"].values())
        result["manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    print(json.dumps({"status": "ok", "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
