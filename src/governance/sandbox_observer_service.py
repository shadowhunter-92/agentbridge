"""Standalone, authenticated sandbox readback observer.

This is a **sandbox-only** process. It reads destination state via an
independent SQLite read-only connection and independently signs observations.
It cannot be enabled in AGENTBRIDGE_ENV=production. For real systems build a
destination-specific authoritative readback adapter and separate key custody.
"""
from __future__ import annotations

import argparse
import hmac
import os
from pathlib import Path
import stat

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .sandbox_readback import SandboxReadOnlyObserver, ObservationUnavailable


class ReadbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    fingerprint: str = Field(min_length=1, max_length=256)


def _restricted_secret(path: str) -> bytes:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise ValueError("observer secret must be a regular non-symlink file")
    if os.name == "posix" and stat.S_IMODE(source.stat().st_mode) & 0o077:
        raise ValueError("observer secrets must not be group/world accessible")
    data = source.read_bytes()
    if not data or len(data) > 4096:
        raise ValueError("missing or oversized observer secret")
    return data


def create_observer_app(*, destination_db: str, destination_key_hex: str,
                        observer_key_file: str, bearer_token_file: str) -> FastAPI:
    """Create the observer process with read-only source and pinned key.

    Independent deployment requires a different OS process, service account
    and filesystem permissions from the destination write authority.
    """
    if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
        raise RuntimeError("sandbox observer cannot run as a production readback service")
    if not isinstance(destination_key_hex, str) or len(destination_key_hex) != 64:
        raise ValueError("pin a valid destination Ed25519 public key")
    try:
        destination_public_key = bytes.fromhex(destination_key_hex)
        if len(destination_public_key) != 32:
            raise ValueError("invalid destination key length")
    except ValueError as exc:
        raise ValueError("pin a valid destination Ed25519 public key") from exc
    private_bytes = _restricted_secret(observer_key_file)
    if len(private_bytes) != 32:
        raise ValueError("observer Ed25519 private key must contain 32 raw bytes")
    signer = Ed25519PrivateKey.from_private_bytes(private_bytes)
    observer_pub = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    if observer_pub == destination_public_key:
        raise ValueError("observer and destination cannot share a key")
    token = _restricted_secret(bearer_token_file)
    if len(token) < 32:
        raise ValueError("observer bearer token must contain at least 32 bytes")
    # Fail at startup if the authoritative source is unavailable.
    with SandboxReadOnlyObserver(destination_db,
                                 destination_public_key_hex=destination_key_hex,
                                 sign=signer.sign):
        pass

    app = FastAPI(title="AgentBridge Sandbox Observer", docs_url=None,
                  redoc_url=None, openapi_url=None)

    @app.post("/v1/sandbox/readback")
    def readback(body: ReadbackRequest, authorization: str | None = Header(default=None)):
        supplied = authorization.removeprefix("Bearer ").encode("utf-8") if (
            authorization and authorization.startswith("Bearer ")) else b""
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="observer authentication required")
        try:
            with SandboxReadOnlyObserver(
                destination_db, destination_public_key_hex=destination_key_hex,
                sign=signer.sign,
            ) as observer:
                receipt, proof = observer.observe(
                    agent_id=body.agent_id, operation_id=body.operation_id,
                    fingerprint=body.fingerprint)
        except ObservationUnavailable:
            # Missing or unverified state is never signed as failed.
            raise HTTPException(status_code=409, detail="outcome unknown or unverified")
        return {"destination_receipt": receipt, "readback_attestation": proof}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Sandbox-only separate readback process")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18767)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        parser.error("sandbox observer must bind to loopback only")
    required = ("AGENTBRIDGE_SANDBOX_DESTINATION_DB",
                "AGENTBRIDGE_SANDBOX_DESTINATION_KEY_HEX",
                "AGENTBRIDGE_SANDBOX_OBSERVER_KEY_FILE",
                "AGENTBRIDGE_SANDBOX_OBSERVER_TOKEN_FILE")
    if any(not os.getenv(name) for name in required):
        parser.error("sandbox observer environment configuration missing")
    app = create_observer_app(
        destination_db=os.environ[required[0]],
        destination_key_hex=os.environ[required[1]],
        observer_key_file=os.environ[required[2]],
        bearer_token_file=os.environ[required[3]])
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
