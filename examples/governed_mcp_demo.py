"""Actual official MCP stdio + existing shared SQL governance, synthetic only.

python -m examples.governed_mcp_demo --output outputs/my-fresh-demo
Type APPROVE at the prompt. No LLM, Stripe, API key or network is required.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import queue
import sqlite3
import sys
import threading
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from src.authority_mode import require_legacy_authority
from src.governance.approvals import ApprovalQueue
from src.governance.audit import AuditLog
from src.governance.budget import Budget, BudgetManager
from src.governance.evidence_cli import verify_bundle
from src.governance.gateway import GovernanceError, GovernanceGateway
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.operation_ledger import OperationConflict, OperationLedger
from src.governance.request_auth import canonical_payload
from src.governance.sandbox_readback import SandboxReadOnlyObserver, ObservationUnavailable
from src.governance.store import SqliteStore

AMOUNT = 1000000  # Integer cents: synthetic USD10,000.00.
ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("success", "lost-ack", "denied", "tool-error", "timeout", "split-brain")


class UncertainToolResult(RuntimeError):
    """No definite successful tool result; do not settle or refund."""


class McpToolFault(UncertainToolResult):
    def __init__(self, result):
        # Retain only exact known synthetic fault markers, never arbitrary
        # target error text in the narrative/evidence.
        texts = [getattr(item, "text", None) for item in result.content]
        self.marker = {
            "Error executing tool transfer_funds: synthetic pre-effect tool failure": "synthetic_pre_effect_error",
            "Error executing tool transfer_funds: committed SQLite destination effect; acknowledgement dropped": "committed_ack_dropped",
        }.get(texts[0]) if len(texts) == 1 else None
        super().__init__("MCP isError: outcome requires readback; no automatic replay")


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def decoded_result(result):
    # Never send isError through the legacy generic success accounting path.
    if result.isError:
        raise McpToolFault(result)
    if not isinstance(result.structuredContent, dict):
        raise UncertainToolResult("structured MCP result required")
    return result.structuredContent


def validate_demo_call(wire):
    """Local demo supports only this exact action, never task augmentation."""
    if (set(wire) != {"jsonrpc", "id", "method", "params"}
            or wire.get("jsonrpc") != "2.0" or wire.get("method") != "tools/call"
            or not isinstance(wire.get("params"), dict)
            or set(wire["params"]) != {"name", "arguments"}
            or wire["params"]["name"] != "transfer_funds"
            or wire["params"]["arguments"] != dict(amount_cents=AMOUNT, currency="usd", recipient="synthetic-design-partner")):
        raise ValueError("exact ordinary synthetic tools/call required; task semantics unsupported")


def approval_prompt(seconds=60):
    print("Human approval required for synthetic transfer $10,000.00 USD.", flush=True)
    print("Type APPROVE within 60 seconds to permit this exact action; anything else denies:", flush=True)
    inbox = queue.Queue(maxsize=1)
    def read():
        try:
            inbox.put(sys.stdin.readline(64))
        except BaseException:
            inbox.put("")
    threading.Thread(target=read, name="bounded-demo-approval", daemon=True).start()
    try:
        return inbox.get(timeout=seconds).strip() == "APPROVE"
    except queue.Empty:
        return False


def check_context():
    require_legacy_authority()  # Preserve refusal of multi-tenant legacy access.
    if os.getenv("AGENTBRIDGE_ENV", "").lower() in {"prod", "production"}:
        raise ValueError("synthetic local demo refuses production")
    if version("mcp") != "1.30.0":
        raise ValueError("reviewed MCP SDK 1.30.0 required")


def child_environment():
    # Official SDK adds only its documented safe defaults. Never forward the
    # caller's environment, credentials, PYTHONPATH or arbitrary executable.
    return {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "AGENTBRIDGE_ENV": "demo", "AGENTBRIDGE_AUTHORITY_MODE": "legacy_single_tenant"}


def effect_count(path):
    if not path.exists():
        return 0
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
        return db.execute("SELECT count(*) FROM sandbox_effects").fetchone()[0]


async def run_demo(output: Path, scenario="success", *, approve=approval_prompt):
    check_context()
    if scenario not in SCENARIOS:
        raise ValueError("known scenario required")
    output = output.resolve()
    output.mkdir()  # Exclusive, retain all earlier attempts, no reset/delete.
    began, events = time.monotonic(), []
    def event(name, **fields):
        row = dict(event=name, elapsed_seconds=round(time.monotonic()-began, 6),
                   utc=datetime.now(timezone.utc).isoformat(), **fields)
        events.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    write_json(output / "claim.json", dict(scenario=scenario, amount_cents=AMOUNT,
        currency="usd", synthetic=True, deterministic_agent=True, llm_used=False,
        production_qualified=False, independent_custody=False, mcp_sdk=version("mcp")))
    event("agent_proposes_transfer", amount_cents=AMOUNT, currency="usd",
          narrative="Deterministic demo client proposes a synthetic $10,000 transfer.")
    agent = AgentIdentity.generate("governed-demo-agent")
    identities_store = SqliteStore(str(output / "governance.sqlite"))
    observer_key = Ed25519PrivateKey.generate()
    target_path = output / "destination.sqlite"
    operation = "demo-operation-" + uuid.uuid4().hex
    wire = dict(jsonrpc="2.0", id="demo-action", method="tools/call",
                params=dict(name="transfer_funds", arguments=dict(amount_cents=AMOUNT,
                currency="usd", recipient="synthetic-design-partner")))
    body = json.dumps(dict(src="mcp", dst="mcp", wire=wire,
        target_id="owned-synthetic-sqlite", operation_id=operation), sort_keys=True).encode()
    signed = canonical_payload(agent.agent_id, "demo-request-nonce", body)
    write_json(output / "signed-request.json", dict(body=json.loads(body), agent_id=agent.agent_id,
        public_key_hex=agent.public_key_hex, nonce="demo-request-nonce", signature_hex=agent.sign(signed).hex()))
    identities = IdentityRegistry(identities_store)
    identities.register(agent)
    budgets = BudgetManager(identities_store)
    budgets.set_budget(agent.agent_id, Budget(spend_limit=AMOUNT, rate_limit=10))
    approvals = ApprovalQueue(identities_store)
    approvals.mark_sensitive("transfer_funds")
    audit = AuditLog(identities_store)
    gateway = GovernanceGateway(identities=identities, budgets=budgets, approvals=approvals, audit=audit)
    gateway.policy.allow_capability(agent.agent_id, "transfer_funds")
    ledger = OperationLedger(identities_store)
    checks, error_type, bundle, verification = {}, None, None, None
    completed = False
    dispatches = 0
    info, protocol = None, None
    try:
        # A fixed module in this checkout; no shell, caller command or credential
        # in argv/env. Official SDK owns stdio shutdown and bounded escalation.
        params = StdioServerParameters(command=sys.executable,
            args=["-B", "-m", "examples.governed_mcp_tool", "--destination", str(target_path),
                  "--scenario", "success" if scenario in {"denied", "split-brain"} else scenario],
            cwd=ROOT, env=child_environment())
        with (output / "mcp-server-stderr.log").open("x", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=8)) as session:
                    init = await session.initialize()
                    protocol = init.protocolVersion
                    tools = await session.list_tools()
                    if {tool.name for tool in tools.tools} != {"describe_demo", "transfer_funds"}:
                        raise ValueError("unexpected demo tools")
                    info = decoded_result(await session.call_tool("describe_demo", {}))
                    if info.get("mcp_sdk") != "1.30.0" or info.get("pid") == os.getpid():
                        raise ValueError("actual separate MCP server required")
                    event("mcp_handshake", protocol=protocol, server_pid=info["pid"],
                          narrative="Official MCP SDK initialized a separate local stdio tool server.")
                    trust = dict(destination_public_key_hex=info["destination_public_key_hex"],
                        observers=[dict(key_id="demo-observer", public_key_hex=public(observer_key), state="active")])
                    write_json(output / "trust-roots.json", trust)

                    def observe():
                        nonlocal bundle, verification
                        entry = ledger.get(agent.agent_id, operation)
                        with SandboxReadOnlyObserver(str(target_path),
                            destination_public_key_hex=trust["destination_public_key_hex"], sign=observer_key.sign) as observer:
                            receipt, proof = observer.observe(agent_id=agent.agent_id, operation_id=operation,
                                                              fingerprint=entry["fingerprint"])
                        expected = dict(agent_id=agent.agent_id, operation_id=operation,
                            fingerprint=entry["fingerprint"], outcome="succeeded",
                            external_reference="sqlite-fenced-effect:" + operation)
                        bundle = dict(receipt=receipt, readback=proof, expected=expected, observer_key_id="demo-observer")
                        verification = verify_bundle(bundle, trust, expected_action=expected)
                        return receipt

                    async def invoke(translated):
                        nonlocal dispatches
                        if (translated.get("method") != "tools/call" or "task" in translated.get("params", {})
                                or translated["params"]["name"] != "transfer_funds"
                                or translated["params"]["arguments"] != wire["params"]["arguments"]):
                            raise ValueError("unsupported or changed demo MCP action")
                        entry = ledger.get(agent.agent_id, operation)
                        expected = dict(agent_id=agent.agent_id, operation_id=operation,
                            fingerprint=entry["fingerprint"], outcome="succeeded",
                            external_reference="sqlite-fenced-effect:" + operation)
                        write_json(output / "expected-action.json", expected)
                        dispatches += 1
                        event("approved_dispatch", amount_cents=AMOUNT, operation_id=operation,
                              narrative="The gateway consumed one approval and reserved exposure before MCP dispatch.")
                        arguments = dict(translated["params"]["arguments"], agent_id=agent.agent_id,
                                         operation_id=operation, fingerprint=entry["fingerprint"])
                        result = await session.call_tool("transfer_funds", arguments,
                            read_timeout_seconds=timedelta(seconds=.5 if scenario == "timeout" else 8))
                        data = decoded_result(result)  # isError always raises before settlement.
                        receipt = observe()  # Only verified separate readback permits success.
                        if data.get("receipt") != receipt:
                            raise UncertainToolResult("MCP reply differs from authoritative signed readback")
                        event("signed_effect_observed", fence_epoch=data["fence_epoch"],
                              narrative="Destination committed one fenced synthetic effect; read-only observer verified it.")
                        return result.model_dump(mode="json")

                    request = dict(agent_id=agent.agent_id, src_proto="mcp", dst_proto="mcp", src_wire=wire,
                        invoke=invoke, cost=AMOUNT, operation_id=operation, target_id="owned-synthetic-sqlite",
                        signed_data=signed, signature=agent.sign(signed), signed_body=body, signed_nonce="demo-request-nonce")
                    validate_demo_call(wire)
                    try:
                        await gateway.route_call(**request)
                    except GovernanceError as refusal:
                        if not refusal.approval_id:
                            raise
                        checks["approval_required_before_dispatch"] = dispatches == 0 and effect_count(target_path) == 0
                        event("approval_required", dispatches=dispatches, effects=0,
                              narrative="Gateway blocked the unapproved transfer before any tool invocation.")
                        approved = await asyncio.to_thread(approve)
                        if scenario == "denied" and approved:
                            raise ValueError("denial scenario requires a denying operator response")
                        if approved:
                            if not approvals.approve(refusal.approval_id):
                                raise ValueError("approval transition refused")
                            event("approval_granted", narrative="Operator input approved this exact synthetic action once.")
                        else:
                            if not approvals.deny(refusal.approval_id):
                                raise ValueError("denial transition refused")
                            checks["denied_without_dispatch"] = dispatches == 0 and ledger.get(agent.agent_id, operation) is None
                            event("approval_denied", narrative="No approved action: no dispatch, effect or spend.")
                    else:
                        raise ValueError("unapproved action dispatched")
                    if approved:
                        try:
                            if scenario == "split-brain":
                                results = await asyncio.gather(gateway.route_call(**request), gateway.route_call(**request), return_exceptions=True)
                                checks["dual_claim_only_one_admitted"] = (sum(not isinstance(r, BaseException) for r in results) == 1
                                    and sum(isinstance(r, (OperationConflict, GovernanceError)) for r in results) == 1 and dispatches == 1)
                                if not checks["dual_claim_only_one_admitted"]:
                                    raise ValueError("dual claim result did not match bounded expectations")
                            else:
                                await gateway.route_call(**request)
                        except Exception as error:
                            error_type = type(error).__name__
                            if scenario in {"success", "split-brain"}:
                                raise
                            expected_fault = (
                                scenario == "lost-ack" and isinstance(error, McpToolFault) and error.marker == "committed_ack_dropped"
                                or scenario == "tool-error" and isinstance(error, McpToolFault) and error.marker == "synthetic_pre_effect_error"
                                or scenario == "timeout" and isinstance(error, McpError) and error.error.code == 408
                                and error.error.message == "Timed out while waiting for response to ClientRequest. Waited 0.5 seconds.")
                            checks["exact_injected_fault_observed"] = bool(expected_fault)
                            if not expected_fault:
                                raise
                            event("uncertain_tool_result", error_type=error_type,
                                  fault_marker=(error.marker if isinstance(error, McpToolFault) else "mcp_request_deadline_0.5_seconds"),
                                  narrative="Tool error or deadline kept UNKNOWN and reserved exposure; no success settlement.")
                        else:
                            if scenario not in {"success", "split-brain"}:
                                raise ValueError("negative scenario unexpectedly settled")
                        try:
                            await gateway.route_call(**request)
                        except OperationConflict:
                            checks["replay_refused_before_dispatch"] = dispatches == 1
                            event("replay_refused", dispatches=dispatches,
                                  narrative="Same operation cannot be automatically dispatched again.")
                        else:
                            raise ValueError("replayed operation admitted")
                        if scenario == "lost-ack":
                            observe()  # Evidence export only: never calls reconciliation.
                            event("lost_ack_readback", narrative="Separate readback found the signed effect; ledger remains UNKNOWN.")
        completed = True
    finally:
        entry = ledger.get(agent.agent_id, operation)
        budget = identities_store.get_budget(agent.agent_id)
        count = effect_count(target_path)
        audit_records = identities_store.load_audit()
        checks["audit_chain_intact"] = AuditLog.verify_chain(audit_records)
        if entry is None:
            checks["denial_accounting"] = dispatches == 0 and count == 0 and budget["spent"] == 0 and not budget["reserved"]
        elif scenario in {"success", "split-brain"}:
            checks["one_verified_effect_settled"] = dispatches == count == 1 and entry["state"] == "succeeded" and budget["spent"] == AMOUNT and not budget["reserved"] and verification is not None
        else:
            checks["unknown_reserved_no_refund"] = entry["state"] == "unknown" and budget["spent"] == 0 and sum(budget["reserved"].values()) == AMOUNT
            checks["expected_effect_count"] = count == (1 if scenario == "lost-ack" else 0)
        if bundle is not None:
            write_json(output / "evidence-bundle.json", bundle)
            write_json(output / "offline-verification.json", verification)
        write_json(output / "audit.json", audit_records)
        write_json(output / "events.json", events)
        summary = dict(scenario=scenario, passed=completed and bool(checks) and all(checks.values()), checks=checks,
            operation_id=operation, operation_state=None if entry is None else entry["state"],
            dispatches=dispatches, effects=count, spent_cents=budget["spent"], reserved_cents=sum(budget["reserved"].values()),
            error_type=error_type, protocol=protocol, mcp_server=info, elapsed_seconds=time.monotonic()-began,
            deterministic_agent=True, llm_used=False, independent_custody=False, production_qualified=False,
            boundary="single operator, local trusted client and synthetic target; separate keys/connections are not independent custody")
        write_json(output / "summary.json", summary)
        identities_store.close()
    event("demo_complete", passed=summary["passed"], state=summary["operation_state"], effects=count,
          spent_cents=summary["spent_cents"], reserved_cents=summary["reserved_cents"],
          narrative="Recorded observed evidence and exact accounting without production claims.")
    # events.json is exclusive, so final event is also retained separately.
    write_json(output / "completion-event.json", events[-1])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="success")
    args = parser.parse_args()
    check_context()
    # Includes approval wait, initialization, invocation and SDK cleanup. Native
    # owned MCP Job handles close on process exit; Compose also sets init:true.
    watchdog = threading.Timer(100, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        result = asyncio.run(run_demo(args.output, args.scenario))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
