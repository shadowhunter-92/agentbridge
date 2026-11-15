"""Read-only container-demo qualification, using durable facts and existing verifier.

Local operator custody only. This never settles, reconciles, refunds or replays.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from src.governance.audit import AuditLog
from src.governance.evidence_cli import verify_bundle
from src.governance.request_auth import canonical_payload

AMOUNT = 1_000_000
MAX_TOTAL_BYTES = 32 * 1024 * 1024
EXPECTED = {
    "success": (1, "succeeded", AMOUNT, 0),
    "lost-ack": (1, "unknown", 0, AMOUNT),
    "denied": (0, None, 0, 0),
    "tool-error": (0, "unknown", 0, AMOUNT),
    "timeout": (0, "unknown", 0, AMOUNT),
    "split-brain": (1, "succeeded", AMOUNT, 0),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    require(len(raw) <= 1024 * 1024, "oversized demonstration evidence")
    return json.loads(raw)


def rows(path, query):
    # SQLite can need writable SHM metadata even for mode=ro WAL reads. Never
    # grant writes to the retained source or use immutable=1 (which ignores WAL).
    # Producers must have exited. Copy DB+WAL exactly into private bounded /tmp;
    # mode=ro can then create auxiliary metadata there, not on the source volume.
    source = path.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="agentbridge-evidence-read-") as temporary:
        copied = Path(temporary) / source.name
        total = 0
        for suffix in ("", "-wal", "-shm"):
            part = Path(str(source) + suffix)
            if part.exists():
                require(part.stat().st_size <= 16 * 1024 * 1024, "oversized SQLite evidence")
                total += part.stat().st_size
                require(total <= MAX_TOTAL_BYTES, "SQLite evidence family exceeds aggregate limit")
                target = Path(str(copied) + suffix)
                shutil.copyfile(part, target)
                require(hashlib.sha256(target.read_bytes()).digest() ==
                        hashlib.sha256(part.read_bytes()).digest(), "copied SQLite bytes differ")
        with closing(sqlite3.connect(copied.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query)]


def source_manifest(directory):
    result = {}
    total = 0
    for path in sorted(directory.iterdir()):
        require(path.is_file() and not path.is_symlink(), "regular evidence files required")
        require(path.stat().st_size <= 16 * 1024 * 1024, "oversized evidence file")
        total += path.stat().st_size
        require(total <= MAX_TOTAL_BYTES, "evidence directory exceeds aggregate limit")
        result[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def inspect_scenario(directory: Path, scenario: str):
    require(scenario in EXPECTED, "unsupported qualification scenario")
    before = source_manifest(directory)
    effects, state, spent, reserved = EXPECTED[scenario]
    summary = read_json(directory / "summary.json")
    claim = read_json(directory / "claim.json")
    request = read_json(directory / "signed-request.json")
    require(summary["scenario"] == claim["scenario"] == scenario, "scenario differs")
    require(summary["passed"] is True and summary["checks"]
            and all(value is True for value in summary["checks"].values()), "producer did not pass")
    require(claim["synthetic"] is True and claim["llm_used"] is False
            and claim["independent_custody"] is False and claim["production_qualified"] is False,
            "unsupported qualification claim")
    require(summary["llm_used"] is False and summary["independent_custody"] is False
            and summary["production_qualified"] is False, "unsupported summary claim")
    body = request["body"]
    require(body["wire"]["params"]["arguments"] == {
        "amount_cents": AMOUNT, "currency": "usd", "recipient": "synthetic-design-partner"},
        "different synthetic action")
    require(body["operation_id"] == summary["operation_id"], "wrong operation identity")
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(request["public_key_hex"])).verify(
        bytes.fromhex(request["signature_hex"]),
        canonical_payload(request["agent_id"], request["nonce"],
                          json.dumps(body, sort_keys=True).encode()))
    governance = directory / "governance.sqlite"
    operations = rows(governance, "SELECT * FROM agent_operations")
    reservations = rows(governance, "SELECT * FROM operation_reservations")
    budgets = rows(governance, "SELECT * FROM budgets")
    approvals = rows(governance, "SELECT * FROM approvals")
    require(len(budgets) == 1 and budgets[0]["agent_id"] == request["agent_id"], "unexpected budgets")
    budget = json.loads(budgets[0]["state"])
    require(budget["spent"] == spent and sum(budget["reserved"].values()) == reserved,
            "durable exposure differs")
    require(len(approvals) == 1 and approvals[0]["status"] ==
            ("denied" if scenario == "denied" else "consumed"), "approval not one-shot")
    expected_operations = 0 if state is None else 1
    require(len(operations) == len(reservations) == expected_operations, "unexpected operation cardinality")
    material = dict(agent_id=request["agent_id"], src=body["src"], dst=body["dst"],
                    wire=body["wire"], cost=float(AMOUNT), target_id=body["target_id"],
                    operation_id=body["operation_id"])
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    require(approvals[0]["agent_id"] == request["agent_id"]
            and approvals[0]["capability"] == "transfer_funds|" + fingerprint
            and approvals[0]["cost"] == AMOUNT, "approval action binding differs")
    if operations:
        operation = operations[0]
        require(operation["state"] == state and operation["fingerprint"] == fingerprint
                and operation["operation_id"] == body["operation_id"]
                and operation["agent_id"] == request["agent_id"], "durable operation differs")
        require(reservations[0]["operation_id"] == body["operation_id"]
                and reservations[0]["agent_id"] == request["agent_id"], "reservation linkage differs")
        if reserved:
            require(budget["reserved"] == {reservations[0]["token"]: AMOUNT},
                    "UNKNOWN reservation linkage differs")
    actual = rows(directory / "destination.sqlite", "SELECT * FROM sandbox_effects")
    require(len(actual) == effects, "durable effect count differs")
    audit = [json.loads(row["entry"]) for row in rows(governance, "SELECT entry FROM audit ORDER BY seq")]
    require(audit == read_json(directory / "audit.json") and AuditLog.verify_chain(audit),
            "durable audit differs or chain broken")
    require(summary["effects"] == effects and summary["operation_state"] == state
            and summary["spent_cents"] == spent and summary["reserved_cents"] == reserved
            and summary["dispatches"] == expected_operations, "summary differs from durable facts")
    require(summary["mcp_server"]["mcp_sdk"] == "1.30.0"
            and summary["mcp_server"]["pid"] > 0, "missing actual MCP server")
    if state is not None:
        require(summary["checks"].get("replay_refused_before_dispatch") is True,
                "duplicate replay was not refused")
    if scenario == "split-brain":
        require(summary["checks"].get("dual_claim_only_one_admitted") is True, "dual claim not qualified")
    if scenario in {"lost-ack", "tool-error", "timeout"}:
        require(summary["checks"].get("exact_injected_fault_observed") is True
                and summary["error_type"] == ("McpError" if scenario == "timeout" else "McpToolFault"),
                "unrelated fault cannot qualify")
    verdict = None
    if effects:
        bundle = read_json(directory / "evidence-bundle.json")
        expected = read_json(directory / "expected-action.json")
        require(actual[0]["fingerprint"] == fingerprint
                and actual[0]["operation_id"] == body["operation_id"]
                and actual[0]["agent_id"] == request["agent_id"]
                and json.loads(actual[0]["receipt_json"]) == bundle["receipt"],
                "readback differs from destination state")
        # Existing verifier retains its 300-second freshness and exact trust binding.
        verdict = verify_bundle(bundle, read_json(directory / "trust-roots.json"),
                                expected_action=expected)
    else:
        require(not (directory / "evidence-bundle.json").exists(),
                "zero-effect scenario must not claim signed success evidence")
    require(source_manifest(directory) == before, "source evidence changed during inspection")
    return dict(scenario=scenario, passed=True, effects=effects, state=state,
                spent_cents=spent, reserved_cents=reserved,
                audit_records=len(audit), verification=verdict, source_sha256=before,
                independent_custody=False, production_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--scenario", choices=EXPECTED, required=True)
    args = parser.parse_args()
    try:
        result = inspect_scenario(args.directory, args.scenario)
    except Exception as error:
        print(json.dumps(dict(passed=False, error_type=type(error).__name__)))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

