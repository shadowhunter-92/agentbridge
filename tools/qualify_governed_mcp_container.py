"""Run owned local Docker CLI scenarios; retain every evidence volume/container.

Build first. No Docker socket is mounted in workloads, no cloud or LLM is used.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

SCENARIOS = ("success", "lost-ack", "denied", "tool-error", "timeout", "split-brain")


def runtime_args(volume, *, readonly_volume=False):
    return ["--network", "none", "--read-only", "--user", "10001:10001",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--pids-limit", "24", "--memory", "512m", "--cpus", "1",
            "--tmpfs", "/tmp:size=64m,mode=1777",
            "--mount", "type=volume,source=" + volume + ",target=/evidence"
            + (",readonly" if readonly_volume else "")]


def inspect_controls(value, volume, *, readonly_volume=False):
    host = value["HostConfig"]
    mounts = [item for item in value["Mounts"] if item["Destination"] == "/evidence"]
    if not (value["Config"]["User"] == "10001:10001"
            and host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True
            and host["PidsLimit"] == 24 and host["Memory"] == 512 * 1024 * 1024
            and host["NanoCpus"] == 1_000_000_000
            and "ALL" in host["CapDrop"] and "no-new-privileges:true" in host["SecurityOpt"]
            and len(mounts) == 1 and mounts[0]["Type"] == "volume"
            and mounts[0]["Name"] == volume and mounts[0]["RW"] is (not readonly_volume)
            and not any(item["Type"] == "bind" for item in value["Mounts"])):
        raise ValueError("container runtime controls differ")
    return True


def docker(*args, input=None, timeout=120, check=True):
    result = subprocess.run(["docker", *args], input=input, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError("docker command failed: " + result.stderr[-2000:])
    return result


def exited_cleanly(details):
    state = details["State"]
    return (state["Status"] == "exited" and state["Running"] is False
            and state["Pid"] == 0 and state["ExitCode"] == 0 and state["OOMKilled"] is False)


def qualify(image, output: Path):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/@-]{0,200}", image):
        raise ValueError("invalid local image reference")
    output.mkdir()  # Never overwrite an earlier trial.
    run_id = uuid.uuid4().hex
    volume = "agentbridge-governed-evidence-" + run_id
    report = dict(passed=False, run_id=run_id, image=image, volume=volume,
                  independent_custody=False, production_qualified=False, scenarios=[])
    def save(name, value):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    try:
        images = json.loads(docker("image", "inspect", image).stdout)
        require_image = images[0]["Id"]
        report["image_id"] = require_image
        save("image-inspect.json", images)
        # Random name plus preflight: never reuse an existing evidence volume.
        if docker("volume", "inspect", volume, check=False).returncode == 0:
            raise ValueError("fresh evidence volume required")
        docker("volume", "create", "--label", "agentbridge.purpose=governed-demo-qualification",
               "--label", "agentbridge.run=" + run_id, volume)
        for scenario in SCENARIOS:
            name = "agentbridge-demo-" + run_id + "-" + scenario
            docker("create", "--pull=never", "--name", name, "--init", "--interactive",
                   "--label", "agentbridge.run=" + run_id, *runtime_args(volume),
                   require_image, "--output", "/evidence/" + scenario, "--scenario", scenario)
            try:
                ran = docker("start", "--attach", "--interactive", name,
                             input="DENY\n" if scenario == "denied" else "APPROVE\n", check=False)
            except subprocess.TimeoutExpired:
                docker("stop", "--time", "2", name, timeout=15, check=False)
                raise
            (output / (scenario + ".stdout.log")).write_text(ran.stdout, encoding="utf-8")
            (output / (scenario + ".stderr.log")).write_text(ran.stderr, encoding="utf-8")
            details = json.loads(docker("inspect", name).stdout)[0]
            save(scenario + ".inspect.json", details)
            inspect_controls(details, volume)
            if ran.returncode != 0 or not exited_cleanly(details):
                if details["State"]["Running"]:
                    docker("stop", "--time", "2", name, timeout=15, check=False)
                raise ValueError("scenario container failed: " + scenario)
            # Check the stopped producer and all volume users before copying.
            # This is a local trusted-operator trial, not a distributed backup proof.
            if docker("ps", "--filter", "volume=" + volume, "--format", "{{.ID}}").stdout.strip():
                raise ValueError("evidence volume still has a running user")
            checker = name + "-readback"
            docker("create", "--pull=never", "--name", checker,
                   "--label", "agentbridge.run=" + run_id,
                   *runtime_args(volume, readonly_volume=True), "--entrypoint", "python",
                   require_image, "-B", "-m", "tools.inspect_governed_mcp_evidence",
                   "--directory", "/evidence/" + scenario, "--scenario", scenario)
            checked = docker("start", "--attach", checker, check=False)
            (output / (scenario + ".readback.stdout.log")).write_text(checked.stdout, encoding="utf-8")
            (output / (scenario + ".readback.stderr.log")).write_text(checked.stderr, encoding="utf-8")
            details = json.loads(docker("inspect", checker).stdout)[0]
            save(scenario + ".readback.inspect.json", details)
            inspect_controls(details, volume, readonly_volume=True)
            observed = json.loads(checked.stdout)
            if checked.returncode != 0 or not exited_cleanly(details) or observed["passed"] is not True:
                raise ValueError("read-only qualification failed: " + scenario)
            save(scenario + ".readback.json", observed)
            report["scenarios"].append(observed)
        report["passed"] = len(report["scenarios"]) == len(SCENARIOS)
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        raise
    finally:
        save("qualification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="agentbridge-governed-mcp-demo:local")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = qualify(args.image, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
