"""Qualification refuses fabricated summaries and weakened container controls."""
import asyncio
import copy
import json
import shutil
import sqlite3

import pytest

from examples.governed_mcp_demo import run_demo
from tools.inspect_governed_mcp_evidence import inspect_scenario, rows, source_manifest
from tools.lock_governed_mcp_demo import render_lock
from tools.qualify_governed_mcp_container import exited_cleanly, inspect_controls, qualify, runtime_args


@pytest.fixture(scope="module")
def success_evidence(tmp_path_factory):
    directory = tmp_path_factory.mktemp("container-inspector") / "actual-success"
    assert asyncio.run(run_demo(directory, approve=lambda: True))["passed"]
    return directory


def test_inspector_accepts_actual_native_evidence(success_evidence):
    result = inspect_scenario(success_evidence, "success")
    assert result["effects"] == 1 and result["spent_cents"] == 1000000
    assert result["verification"]["verdict"] == "signature_and_binding_verified"
    assert result["independent_custody"] is False


def test_sqlite_copy_reader_preserves_uncheckpointed_wal_without_opening_source(tmp_path, monkeypatch):
    source = tmp_path / "stopped.sqlite"
    connection = sqlite3.connect(source)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE exact_bytes(value TEXT)")
        connection.execute("INSERT INTO exact_bytes VALUES('committed-in-WAL')")
        connection.commit()
        before = source_manifest(tmp_path)
        original = sqlite3.connect
        def private_only(path, **kwargs):
            assert str(source.resolve().as_uri()) not in str(path)
            assert "mode=ro" in str(path) and "immutable" not in str(path)
            return original(path, **kwargs)
        monkeypatch.setattr("tools.inspect_governed_mcp_evidence.sqlite3.connect", private_only)
        assert rows(source, "SELECT * FROM exact_bytes") == [{"value": "committed-in-WAL"}]
        assert source_manifest(tmp_path) == before
    finally:
        connection.close()


def test_evidence_aggregate_byte_limit_refuses_before_hashing(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.inspect_governed_mcp_evidence.MAX_TOTAL_BYTES", 1000)
    for index in range(3):
        (tmp_path / str(index)).write_bytes(b"x" * 400)
    with pytest.raises(ValueError, match="aggregate"):
        source_manifest(tmp_path)


def test_sqlite_copy_bytes_must_match_source(tmp_path, monkeypatch):
    source = tmp_path / "original.sqlite"
    source.write_bytes(b"bounded original evidence")
    def corrupt_copy(original, target):
        target.write_bytes(b"different bytes")
    monkeypatch.setattr("tools.inspect_governed_mcp_evidence.shutil.copyfile", corrupt_copy)
    with pytest.raises(ValueError, match="copied SQLite bytes differ"):
        rows(source, "SELECT 1")
    assert source.read_bytes() == b"bounded original evidence"


@pytest.mark.parametrize("scenario", ["lost-ack", "denied", "tool-error", "timeout", "split-brain"])
def test_inspector_checks_actual_negative_accounting(tmp_path, scenario):
    directory = tmp_path / scenario
    assert asyncio.run(run_demo(directory, scenario, approve=lambda: scenario != "denied"))["passed"]
    result = inspect_scenario(directory, scenario)
    assert result["passed"]
    assert result["reserved_cents"] == (1000000 if scenario in {"lost-ack", "tool-error", "timeout"} else 0)


@pytest.mark.parametrize("mutation", ["budget", "ledger", "approval", "effect", "summary", "signature", "request", "audit"])
def test_inspector_rejects_inconsistent_facts_even_with_passed_summary(success_evidence, tmp_path, mutation):
    directory = tmp_path / "changed"
    shutil.copytree(success_evidence, directory)
    if mutation in {"budget", "ledger", "approval", "audit"}:
        with sqlite3.connect(directory / "governance.sqlite") as db:
            if mutation == "budget":
                row = db.execute("SELECT state FROM budgets").fetchone()
                state = json.loads(row[0])
                state["spent"] = 0
                db.execute("UPDATE budgets SET state=?", (json.dumps(state),))
            elif mutation == "ledger":
                db.execute("UPDATE agent_operations SET state='unknown'")
            elif mutation == "approval":
                db.execute("UPDATE approvals SET capability='a-different-action'")
            else:
                db.execute("DELETE FROM audit")
    elif mutation == "effect":
        with sqlite3.connect(directory / "destination.sqlite") as db:
            db.execute("DELETE FROM sandbox_effects")
    else:
        name = {"summary": "summary.json", "signature": "evidence-bundle.json",
                "request": "signed-request.json"}[mutation]
        path = directory / name
        data = json.loads(path.read_bytes())
        if mutation == "summary":
            data["reserved_cents"] = 1000000
        elif mutation == "signature":
            data["receipt"]["signature_hex"] = "00" * 64
        else:
            data["body"]["wire"]["params"]["arguments"]["amount_cents"] = 1
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises((ValueError, KeyError)):
        inspect_scenario(directory, "success")


def controls(readonly=False):
    return {"Config": {"User": "10001:10001"},
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True,
                           "PidsLimit": 24, "Memory": 512 * 1024 * 1024, "NanoCpus": 1000000000,
                           "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"]},
            "Mounts": [{"Destination": "/evidence", "Type": "volume", "Name": "owned",
                        "RW": not readonly}]}


def test_runtime_arguments_and_both_mount_modes():
    for readonly in (False, True):
        assert inspect_controls(controls(readonly), "owned", readonly_volume=readonly)
        args = runtime_args("owned", readonly_volume=readonly)
        assert args[args.index("--network") + 1] == "none"
        assert args[args.index("--user") + 1] == "10001:10001"
        assert args[-1].endswith(",readonly") is readonly


@pytest.mark.parametrize("field,value", [("Status", "running"), ("Running", True),
    ("Pid", 42), ("ExitCode", 1), ("OOMKilled", True)])
def test_readback_requires_a_truly_exited_clean_producer(field, value):
    state = dict(Status="exited", Running=False, Pid=0, ExitCode=0, OOMKilled=False)
    assert exited_cleanly({"State": state})
    state[field] = value
    assert not exited_cleanly({"State": state})


@pytest.mark.parametrize("field,value", [
    ("NetworkMode", "bridge"), ("ReadonlyRootfs", False), ("PidsLimit", 0),
    ("Memory", 0), ("NanoCpus", 0), ("CapDrop", []), ("SecurityOpt", []),
])
def test_runtime_inspection_refuses_weaker_controls(field, value):
    observed = controls()
    observed["HostConfig"][field] = value
    with pytest.raises(ValueError):
        inspect_controls(observed, "owned")


@pytest.mark.parametrize("mutation", ["root", "bind", "wrong-volume", "writable-readback"])
def test_runtime_inspection_refuses_root_or_untrusted_mount(mutation):
    observed = controls(True)
    if mutation == "root":
        observed["Config"]["User"] = "0:0"
    elif mutation == "bind":
        observed["Mounts"][0]["Type"] = "bind"
    elif mutation == "wrong-volume":
        observed["Mounts"][0]["Name"] = "another"
    else:
        observed["Mounts"][0]["RW"] = True
    with pytest.raises(ValueError):
        inspect_controls(observed, "owned", readonly_volume=True)


def resolution():
    return {"environment": {"sys_platform": "linux", "python_version": "3.12",
                            "platform_machine": "x86_64", "implementation_name": "cpython"},
            "install": [{"metadata": {"name": "mcp", "version": "1.30.0"},
                         "download_info": {"url": "https://files.pythonhosted.org/mcp.whl",
                                           "archive_info": {"hashes": {"sha256": "a" * 64}}}}]}


def test_lock_renderer_is_deterministic_and_hash_bound():
    report = resolution()
    assert render_lock(report, "") == render_lock(report, "")
    assert "mcp==1.30.0 --hash=sha256:" in render_lock(report, "")
    assert "Runtime constraints UTF-8/LF SHA256:" in render_lock(report, "")
    assert "mcp==1.30.0 --hash" not in render_lock(report, "mcp==1.30.0\n")


@pytest.mark.parametrize("mutation", ["platform", "sdk", "hash", "source", "duplicate", "runtime-conflict"])
def test_lock_renderer_refuses_unreviewed_graph(mutation):
    report = copy.deepcopy(resolution())
    runtime = ""
    package = report["install"][0]
    if mutation == "platform":
        report["environment"]["platform_machine"] = "aarch64"
    elif mutation == "sdk":
        package["metadata"]["version"] = "1.29.0"
    elif mutation == "hash":
        package["download_info"]["archive_info"]["hashes"]["sha256"] = "unverified"
    elif mutation == "source":
        package["download_info"]["url"] = "https://other.invalid/mcp.whl"
    elif mutation == "duplicate":
        report["install"].append(copy.deepcopy(package))
    else:
        runtime = "mcp==1.29.0\n"
    with pytest.raises(ValueError):
        render_lock(report, runtime)


def test_invalid_image_and_existing_output_refuse_before_docker(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Docker must not run")
    monkeypatch.setattr("tools.qualify_governed_mcp_container.docker", forbidden)
    with pytest.raises(ValueError):
        qualify("--privileged", tmp_path / "unused")
    with pytest.raises(FileExistsError):
        qualify("owned:local", tmp_path)

