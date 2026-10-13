#!/usr/bin/env python3
"""Operate an existing *disposable* two-host AWS PostgreSQL acceptance lab.

No infrastructure is created. The full phase sequence is over SSM RunCommand.
Any failure terminates both verified AgentBridge-tagged instances and deletes
the known ephemeral credentials. Does not create/store database passwords.
The default is a no-network dry run; --execute requires an existing Free plan.
This script does NOT confer independent administrative key custody.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import re
import time

PHASES = [
    ("primary-init", "primary"),
    ("standby-init", "standby"),
    ("old-leader", "primary"),
    ("new-leader", "standby"),
    ("reject-old", "primary"),
    ("observe", "standby"),
    ("replica-check", "standby"),
    ("stop-primary", "primary"),
    ("promote", "standby"),
    ("upgrade-rollback", "standby"),
]
SHA = re.compile(r"^[0-9a-f]{40}$")
INSTANCE = re.compile(r"^i-[0-9a-f]{8,17}$")
PREFIX = re.compile(r"^/agentbridge/ephemeral-[a-z0-9-]{6,60}$")


def validate(a):
    for field in ("harness_sha", "candidate_sha", "baseline_sha"):
        if not SHA.fullmatch(getattr(a, field)):
            raise ValueError(field + " must be an immutable lowercase 40-character Git SHA")
    if not PREFIX.fullmatch(a.parameter_prefix):
        raise ValueError("parameter prefix must be a bounded dedicated lab namespace")
    if a.primary_id == a.standby_id:
        raise ValueError("hosts must be distinct")
    for value in (a.primary_id, a.standby_id):
        if not INSTANCE.fullmatch(value):
            raise ValueError("invalid EC2 instance ID")
    for value in (a.primary_ip, a.standby_ip):
        address = ipaddress.ip_address(value)
        if address.version != 4 or not address.is_private:
            raise ValueError("private IPv4 addresses required for this lab")
        if (address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_reserved):
            raise ValueError("usable private VPC address required")
    if a.primary_ip == a.standby_ip:
        raise ValueError("different host IPs required")
    if a.region != "us-east-1":
        raise ValueError("pinned lab region is us-east-1")


def commands(a, phase):
    env = [
        "set -euo pipefail",
        "export AB_LAB_PREFIX=" + a.parameter_prefix,
        "export AB_PRIMARY_IP=" + a.primary_ip,
        "export AB_STANDBY_IP=" + a.standby_ip,
        "export AB_SOURCE_SHA=" + a.candidate_sha,
    ]
    if phase == "upgrade-rollback":
        return env + [
            "export AB_BASELINE_SHA=" + a.baseline_sha,
            "export AB_CANDIDATE_SHA=" + a.candidate_sha,
            "curl -fsSL --retry 3 --max-time 50 "
            "https://raw.githubusercontent.com/shadowhunter-92/agentbridge/"
            + a.harness_sha + "/tools/aws_pg_upgrade_rollback.sh -o /tmp/ab-rollback.sh",
            "bash -n /tmp/ab-rollback.sh",
            "bash /tmp/ab-rollback.sh",
        ]
    return env + [
        "curl -fsSL --retry 3 --max-time 50 "
        "https://raw.githubusercontent.com/shadowhunter-92/agentbridge/"
        + a.harness_sha + "/tools/aws_pg_two_host_acceptance.sh -o /tmp/ab-two-host.sh",
        "bash -n /tmp/ab-two-host.sh",
        "bash /tmp/ab-two-host.sh " + phase,
    ]


def assert_disposable_instances(ec2, a):
    desc = ec2.describe_instances(InstanceIds=[a.primary_id, a.standby_id])
    found = {}
    for reservation in desc["Reservations"]:
        for inst in reservation["Instances"]:
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            if tags.get("Project") != "AgentBridge" or tags.get("Experiment") != "two-host-controlled-pg":
                raise RuntimeError("instance is not tagged as this disposable experiment")
            if inst["State"]["Name"] != "running":
                raise RuntimeError("lab instance must be running")
            found[inst["InstanceId"]] = inst
    if set(found) != {a.primary_id, a.standby_id}:
        raise RuntimeError("missing one of the expected lab hosts")
    if found[a.primary_id]["PrivateIpAddress"] != a.primary_ip:
        raise RuntimeError("primary IP does not match AWS inventory")
    if found[a.standby_id]["PrivateIpAddress"] != a.standby_ip:
        raise RuntimeError("standby IP does not match AWS inventory")


def wait_command(ssm, command_id, instance_id, timeout=520):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            d = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(2)
            continue
        if d["Status"] in ("Success", "Failed", "TimedOut", "Cancelled", "Cancelling"):
            return d
        time.sleep(4)
    raise TimeoutError("SSM command phase timed out")


def cleanup(ec2, ssm, a):
    result = {"credentials_deleted": False, "termination_requested": False}
    names = [a.parameter_prefix + "/writer", a.parameter_prefix + "/replication"]
    try:
        d = ssm.delete_parameters(Names=names)
        result["credentials_deleted"] = set(d.get("DeletedParameters", [])) == set(names)
        result["missing_parameter_names"] = d.get("InvalidParameters", [])
    except Exception as exc:
        result["credential_cleanup_error_type"] = type(exc).__name__
    try:
        ec2.terminate_instances(InstanceIds=[a.primary_id, a.standby_id])
        result["termination_requested"] = True
        waiter = ec2.get_waiter("instance_terminated")
        waiter.wait(InstanceIds=[a.primary_id, a.standby_id], WaiterConfig={"Delay":6, "MaxAttempts":25})
        result["instances_terminated"] = True
    except Exception as exc:
        result["termination_error_type"] = type(exc).__name__
        result["instances_terminated"] = False
    return result


def run(a):
    validate(a)
    prepared = [{"phase": phase, "host": host} for phase, host in PHASES]
    if not a.execute:
        print(json.dumps({
            "mode": "offline-dry-run", "aws_called": False, "instances_created": False,
            "phase_order": prepared, "on_execute_cleanup": "terminate both instances; delete scoped secrets",
        }, indent=2))
        return 0
    import boto3
    session = boto3.Session(region_name=a.region)
    ec2, ssm = session.client("ec2"), session.client("ssm")
    plan = session.client("freetier").get_account_plan_state()
    if plan.get("accountPlanType") != "FREE" or plan.get("accountPlanStatus") != "ACTIVE":
        raise RuntimeError("AWS plan is not ACTIVE FREE; refusing lab")
    assert_disposable_instances(ec2, a)
    evidence = {
        "source": "AWS SSM operated ephemeral two-host acceptance",
        "candidate_sha": a.candidate_sha,
        "baseline_sha": a.baseline_sha,
        "harness_sha": a.harness_sha,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "phases": [],
        "all_phases_passed": False,
    }
    try:
        deadline = time.monotonic() + (28 * 60)
        for phase, actor in PHASES:
            if time.monotonic() >= deadline:
                raise TimeoutError("global staging trial deadline exceeded")
            host = a.primary_id if actor == "primary" else a.standby_id
            cmd = ssm.send_command(
                InstanceIds=[host], DocumentName="AWS-RunShellScript",
                Parameters={"commands": commands(a, phase)},
                TimeoutSeconds=540,
                Comment="Disposable AgentBridge qualification phase: " + phase,
            )["Command"]["CommandId"]
            outcome = wait_command(ssm, cmd, host)
            event = {
                "phase": phase,
                "host_role": actor,
                "ssm_command_id": cmd,
                "status": outcome["Status"],
                "started": outcome.get("ExecutionStartDateTime"),
                "finished": outcome.get("ExecutionEndDateTime"),
            }
            # Preserve only predefined success markers; never attach arbitrary
            # stdout which might contain credentials or private data.
            markers = (
                "PRIMARY_READY", "STANDBY_REPLAYING", "OLD_LEADER_EPOCH",
                "NEW_EPOCH", "STALE_OLD_LEADER_DENIED",
                "READBACK_READONLY_OBSERVER_SIGNATURE_VERIFIED",
                "REPLICATED_EFFECT_PRESENT", "PRIMARY_STOPPED",
                "PHYSICAL_REPLICA_PROMOTED", "PROMOTE_TO_SQL_MS",
                "APPLICATION_ARTIFACT_UPGRADE_ROLLBACK_ACCEPTED",
            )
            event["markers"] = [
                line.strip()[:180] for line in outcome.get("StandardOutputContent", "").splitlines()
                if any(marker in line for marker in markers)
            ]
            evidence["phases"].append(event)
            if outcome["Status"] != "Success":
                raise RuntimeError("phase " + phase + " failed; consult SSM command ID")
        evidence["all_phases_passed"] = True
    finally:
        evidence["cleanup"] = cleanup(ec2, ssm, a)
        evidence["finished_utc"] = datetime.now(timezone.utc).isoformat()
        # Never print or store plaintext passwords or observer private keys.
        with open(a.evidence_file, "w", encoding="utf-8") as output:
            json.dump(evidence, output, indent=2)
        print(json.dumps(evidence, indent=2))
    return 0 if evidence["all_phases_passed"] and evidence["cleanup"].get("instances_terminated") else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--primary-id", required=True)
    p.add_argument("--standby-id", required=True)
    p.add_argument("--primary-ip", required=True)
    p.add_argument("--standby-ip", required=True)
    p.add_argument("--parameter-prefix", required=True)
    p.add_argument("--harness-sha", required=True)
    p.add_argument("--candidate-sha", required=True)
    p.add_argument("--baseline-sha", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--evidence-file", default="aws-two-host-evidence.json")
    p.add_argument("--execute", action="store_true", help="Requires existing tagged lab instances; will terminate them")
    a = p.parse_args()
    raise SystemExit(run(a))


if __name__ == "__main__":
    main()
