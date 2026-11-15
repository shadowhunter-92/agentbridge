"""Render a reviewed Alpine/Python3.12/x86_64 MCP wheel resolution as strict pins.

Resolve with pip --dry-run --ignore-installed --only-binary=:all: in the exact
pinned demo base, using version-only runtime constraints. Final installation
must combine this lock and requirements-runtime.lock with --require-hashes.
This parser performs no network requests or package installation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def render_lock(report, runtime):
    environment = report["environment"]
    if not (environment["sys_platform"] == "linux" and environment["python_version"] == "3.12"
            and environment["platform_machine"] == "x86_64"
            and environment["implementation_name"] == "cpython"):
        raise ValueError("requires the reviewed Linux CPython3.12 x86_64 resolution")
    pins = dict((normalized(name), version) for name, version in re.findall(
        r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", runtime, re.MULTILINE))
    packages = {}
    for item in report["install"]:
        name, version = item["metadata"]["name"], item["metadata"]["version"]
        name = normalized(name)
        url = urlsplit(item["download_info"]["url"])
        digest = item["download_info"]["archive_info"]["hashes"]["sha256"]
        if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                or not re.fullmatch(r"[A-Za-z0-9.+!-]+", version)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or url.scheme != "https" or url.hostname != "files.pythonhosted.org"
                or not url.path.endswith(".whl") or name in packages):
            raise ValueError("requires unique hashed official PyPI wheels")
        if name in pins and version != pins[name]:
            raise ValueError("runtime lock conflict: " + name)
        packages[name] = (version, digest)
    if packages.get("mcp", (None,))[0] != "1.30.0":
        raise ValueError("reviewed MCP1.30.0 is required")
    lines = [
        "# Reviewed demo-only supplemental closure; generated with tools/lock_governed_mcp_demo.py.",
        "# Target: pinned python:3.12-alpine3.22, CPython3.12, Linux musl x86_64 only.",
        "# Runtime constraints UTF-8/LF SHA256: " + hashlib.sha256(runtime.encode()).hexdigest(),
        "# Install TOGETHER with requirements-runtime.lock, --require-hashes --only-binary=:all:.",
        "# Does not qualify other platforms, release provenance or production operation.",
        "",
    ]
    # Existing runtime pins/hashes are enforced by the combined installation.
    # Duplicating them here would create a second owner for security updates.
    lines += [name + "==" + version + " --hash=sha256:" + digest
              for name, (version, digest) in sorted(packages.items()) if name not in pins]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=Path("requirements-runtime.lock"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = render_lock(json.loads(args.report.read_bytes()), args.runtime.read_text(encoding="utf-8"))
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(result)


if __name__ == "__main__":
    main()

