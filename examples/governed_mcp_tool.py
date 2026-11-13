"""Synthetic MCP destination. Private signing key exists only in this process.

The owner of these local pipes is trusted. This is not a remotely deployable
authorization service, Stripe API, payment system or hostile-code sandbox.
"""
from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from src.authority_mode import require_legacy_authority
from src.governance.fenced_sqlite_destination import FencedSqliteTarget


def tool_result(data):
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, sort_keys=True))],
                          structuredContent=data, isError=False)


def main():
    require_legacy_authority()
    if os.getenv("AGENTBRIDGE_ENV", "").lower() in {"prod", "production"}:
        raise SystemExit("synthetic local demo refuses production")
    if version("mcp") != "1.30.0":
        raise SystemExit("this demo requires reviewed MCP SDK 1.30.0")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--scenario", choices=("success", "lost-ack", "tool-error", "timeout"), required=True)
    args = parser.parse_args()
    if args.destination.exists():
        raise SystemExit("fresh destination required; never reset existing evidence")
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    server = FastMCP("agentbridge-governed-synthetic-transfer", log_level="WARNING")
    # Async tools execute on this event loop, matching this SQLite connection.
    with FencedSqliteTarget(str(args.destination), sign=key.sign) as target:
        @server.tool()
        async def describe_demo() -> CallToolResult:
            """Public identity of this synthetic single-authority destination."""
            return tool_result(dict(destination_public_key_hex=public, pid=os.getpid(),
                        python_executable=sys.executable, mcp_sdk=version("mcp"),
                        scope="synthetic-local-single-authority", currency="usd", amount_cents=1000000))

        @server.tool()
        async def transfer_funds(amount_cents: int, currency: str, recipient: str,
                                 agent_id: str, operation_id: str, fingerprint: str) -> CallToolResult:
            """Record a synthetic $10,000 transfer; never moves real money."""
            if (type(amount_cents) is not int or amount_cents != 1000000 or currency != "usd"
                    or recipient != "synthetic-design-partner" or agent_id != "governed-demo-agent"
                    or not re.fullmatch(r"demo-operation-[0-9a-f]{32}", operation_id)
                    or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)):
                raise ValueError("exact synthetic demonstration action required")
            if args.scenario == "tool-error":
                raise RuntimeError("synthetic pre-effect tool failure")
            if args.scenario == "timeout":
                # Client has a shorter declared deadline. Cancellation precedes
                # the effect here; UNKNOWN is still retained by the gateway.
                await asyncio.sleep(3)
            scope, owner = "demo-" + operation_id, "owned-mcp-tool"
            epoch = target.acquire(scope=scope, owner=owner, ttl_seconds=15)
            receipt = target.commit(scope=scope, owner=owner, epoch=epoch,
                                    agent_id=agent_id, operation_id=operation_id,
                                    fingerprint=fingerprint, lose_ack=args.scenario == "lost-ack")
            return tool_result(dict(receipt=receipt, fence_epoch=epoch, synthetic=True))

        server.run(transport="stdio")


if __name__ == "__main__":
    main()
