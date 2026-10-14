#!/usr/bin/env python3
"""Owner-run GitHub ruleset bootstrap; uses existing `gh auth login` credentials.

Usage:
  python tools/protect_github_repository.py
  python tools/protect_github_repository.py --apply
No PAT, token or password is accepted as an argument or stored in this script.
The owner should revoke any previously pasted PAT before running.
"""
import argparse
import json
import subprocess
import sys

REPO = "shadowhunter-92/agentbridge"
NAME = "AgentBridge protected main and release branches"
TARGETS = ["refs/heads/main", "refs/heads/release/*", "refs/heads/integration/*"]


def gh(method, path, payload=None):
    cmd = ["gh", "api", "--method", method, "--header", "Accept: application/vnd.github+json", path]
    if payload is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("GitHub API request failed; check gh auth status, token permissions, "
                           "and repository plan. Error details withheld to avoid exposing secrets.")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create this ruleset after owner review")
    args = parser.parse_args()
    current = gh("GET", "repos/" + REPO + "/rulesets")
    existing = [x for x in current if x.get("name") == NAME]
    if existing:
        print("Already present: " + NAME + " (id=" + str(existing[0].get("id")) + ")")
        return 0
    # A solo maintainer cannot approve their own PRs. This initial policy
    # requires PRs but intentionally sets approvals to zero. After adding a
    # second trusted maintainer, enforce required_code_owner_review=True.
    payload = {
        "name": NAME,
        "target": "branch",
        "enforcement": "active",
        "source_type": "Repository",
        "conditions": {"ref_name": {"include": TARGETS, "exclude": []}},
        "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {
                "dismiss_stale_reviews_on_push": True,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
                "required_approving_review_count": 0,
                "required_review_thread_resolution": True
            }},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [
                    {"context": "test (3.11)"},
                    {"context": "test (3.12)"}
                ]
            }}
        ]
    }
    print(json.dumps(payload, indent=2))
    if not args.apply:
        print("DRY RUN only. Use --apply after verifying branches and CI check names.")
        return 0
    created = gh("POST", "repos/" + REPO + "/rulesets", payload)
    rid = created.get("id")
    if not rid:
        raise RuntimeError("No ruleset id returned")
    checked = gh("GET", "repos/" + REPO + "/rulesets/" + str(rid))
    if checked.get("enforcement") != "active":
        raise RuntimeError("Ruleset created but was not confirmed active")
    print("Verified ACTIVE GitHub ruleset id:", rid)
    print("Important: enable secret scanning and push protection separately in GitHub Settings.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
        print("FAILED:", str(exc), file=sys.stderr)
        raise SystemExit(1)
