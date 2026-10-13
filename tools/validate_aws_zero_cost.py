#!/usr/bin/env python3
"""Offline validation of AWS $0 staging audit configuration. No AWS calls."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
template=json.loads((ROOT/"infra/aws/staging-audit-only.template.json").read_text())
role=template["Resources"]["AgentBridgeStagingAuditRole"]["Properties"]
trust=role["AssumeRolePolicyDocument"]["Statement"]
assert len(trust)==1
statement=trust[0]
assert statement["Action"]=="sts:AssumeRoleWithWebIdentity"
conditions=statement["Condition"]["StringEquals"]
assert conditions["token.actions.githubusercontent.com:aud"]=="sts.amazonaws.com"
assert conditions["token.actions.githubusercontent.com:sub"]=="repo:shadowhunter-92/agentbridge:ref:refs/heads/integration/r4-main-reconciliation-2026-10"
assert role["MaxSessionDuration"]<=3600
all_actions=set()
for policy in role["Policies"]:
    for item in policy["PolicyDocument"]["Statement"]:
        assert item["Effect"]=="Allow"
        all_actions.update(item["Action"])
assert all(x.startswith(("eks:List","eks:Describe","rds:Describe","ec2:Describe")) for x in all_actions)
assert not any(x.lower().startswith(("iam:", "sts:", "s3:put", "ec2:run", "eks:create","rds:create")) for x in all_actions)
assert set(template["Resources"])=={"AgentBridgeStagingAuditRole"}
print("AWS zero-cost template static security preflight: PASS (no AWS resources created)")
