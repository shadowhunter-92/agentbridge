"""Opt-in disposable local PostgreSQL + reviewed-image startup qualification.

Creates only randomly named local containers/network and removes those exact
resources. Never provisions cloud services, publishes an image or uses a supplied
database. This is a bounded deployment smoke check, not production acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def docker(*args):
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if proc.returncode:
        raise RuntimeError("local Docker operation failed: " + proc.stderr[-1200:])
    return proc.stdout.strip()


def qualify(image):
    if os.getenv("AGENTBRIDGE_DISPOSABLE_IMAGE_QUALIFICATION") != "1" or \
            not re.fullmatch(r"agentbridge:[A-Za-z0-9_.-]+", image):
        raise ValueError("explicit disposable local image qualification required")
    suffix = uuid.uuid4().hex[:12]
    network = "agentbridge-image-qual-" + suffix
    database, application = network + "-pg", network + "-app"
    password, admin = secrets.token_hex(24), secrets.token_hex(32)
    resources = []
    report = None
    try:
        resources.append(("network", network))
        docker("network", "create", "--label", "codex.task=agentbridge-image-qualification", network)
        resources.append(("container", database))
        docker("run", "-d", "--name", database, "--network", network,
               "--label", "codex.task=agentbridge-image-qualification",
               "-e", "POSTGRES_USER=agentbridge", "-e", "POSTGRES_DB=agentbridge_test",
               "-e", "POSTGRES_PASSWORD=" + password, "postgres:16")
        for _ in range(100):
            try:
                docker("exec", database, "pg_isready", "-U", "agentbridge", "-d", "agentbridge_test")
                break
            except RuntimeError:
                time.sleep(0.2)
        else:
            raise RuntimeError("disposable PostgreSQL readiness timed out")
        resources.append(("container", application))
        docker("run", "-d", "--name", application, "--network", network,
               "--label", "codex.task=agentbridge-image-qualification",
               "--read-only", "--cap-drop=ALL", "--security-opt", "no-new-privileges:true",
               "--tmpfs", "/tmp:rw,nosuid,noexec,size=64m", "--memory", "256m",
               "-p", "127.0.0.1::8000", "-e", "AGENTBRIDGE_ENV=production",
               "-e", "AGENTBRIDGE_ADMIN_KEY=" + admin,
               "-e", f"AGENTBRIDGE_DB=postgresql://agentbridge:{password}@{database}:5432/agentbridge_test",
               image)
        port = docker("port", application, "8000/tcp").rsplit(":", 1)[-1]
        origin = "http://127.0.0.1:" + port
        # Explicitly bypass ambient proxies for the local synthetic check.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, body=None, key=None):
            headers = {"Content-Type": "application/json"}
            if key:
                headers["X-Admin-Key"] = key
            req = urllib.request.Request(origin + path,
                data=json.dumps(body).encode() if body is not None else None, headers=headers)
            try:
                with opener.open(req, timeout=2) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read())
        for _ in range(100):
            try:
                status, health = request("/ready")
                if status == 200:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("review image readiness timed out")
        checks = {
            "production_postgres_ready": health["store"]["type"] == "PostgresStore" and health["store"]["ok"],
            "operator_auth_required": request("/control/identities")[0] == 401,
            "wrong_operator_key_denied": request("/control/identities", key="invalid")[0] == 401,
            "configured_operator_key_accepted": request("/control/identities", key=admin)[0] == 200,
            "unsupported_mcp_procedure_rejected": request("/control/translate/call", {
                "src": "mcp", "dst": "a2a", "wire": {"method": "resources/read", "params": {"uri": "synthetic"}}
            })[0] == 400,
            "offline_verifier_installed": "--expected" in docker("exec", application, "agentbridge-verify-evidence", "--help"),
        }
        if not all(checks.values()):
            raise AssertionError("image qualification checks failed: " + json.dumps(checks))
        report = {"classification": "local_disposable_image_smoke_not_production_acceptance",
                "image": image, "image_id": docker("image", "inspect", "--format", "{{.Id}}", image),
                "checks": checks}
        return report
    except Exception as exc:
        logs = subprocess.run(["docker", "logs", application], capture_output=True, text=True)
        detail = (logs.stdout + logs.stderr)[-2400:].replace(password, "[redacted]").replace(admin, "[redacted]")
        raise RuntimeError(str(exc) + "\nSanitized application log:\n" + detail) from exc
    finally:
        for kind, name in reversed(resources):
            if kind == "container":
                subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)
            else:
                subprocess.run(["docker", "network", "rm", name], capture_output=True)
        left_containers = set(docker("ps", "-a", "--format", "{{.Names}}").splitlines())
        left_networks = set(docker("network", "ls", "--format", "{{.Name}}").splitlines())
        if any(name in (left_containers if kind == "container" else left_networks) for kind, name in resources):
            raise RuntimeError("disposable image qualification cleanup incomplete")
        if report is not None:
            report["cleanup_verified"] = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.image), indent=2))
