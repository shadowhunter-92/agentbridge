"""Offline CLI uses enrolled platform authority and the same migration API."""

import json

import pytest

from src.governance.store import SqliteStore
from src.governance.tenant_migration_cli import main
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_migration import backup_restore as backup_restore
from tests.test_tenant_migration import historical as historical
from tests.test_tenant_store import namespaces as namespaces


def _store_config(store):
    if isinstance(store, SqliteStore):
        return {"backend": "sqlite", "path": store._db.execute("PRAGMA database_list").fetchone()["file"]}
    from psycopg.conninfo import make_conninfo

    return {"backend": "postgres", "dsn": make_conninfo(store._db.info.dsn, password=store._db.info.password)}


@pytest.fixture
def operator_config(authority, historical, tmp_path, monkeypatch):
    directory, _, token, _, _ = authority
    config = {
        "operator_issuer": ISSUER,
        "authority": {
            "store": _store_config(directory.store),
            "audience": "agentbridge-authority",
            "public_key_pem": directory.verifiers[ISSUER].config.public_key_pem,
        },
        "source": _store_config(historical[0]),
    }
    path = tmp_path / "operator-private.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("AGENTBRIDGE_OPERATOR_TOKEN", token("owner"))
    return config, path


def test_cli_freeze_verify_activate_and_safe_rollback(operator_config, backup_restore, namespaces, capsys):
    config, path = operator_config
    assert main(["--config", str(path), "freeze", "--tenant", "alpha"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["phase"] == "frozen"
    restored, archive = backup_restore()
    config["restored"] = _store_config(restored)
    path.write_text(json.dumps(config), encoding="utf-8")
    for action in ("verify-backup", "activate"):
        assert main(["--config", str(path), action, "--archive", str(archive)]) == 0
        output = capsys.readouterr().out
        assert json.loads(output)["status"] == "ok"
        assert "local-tenant-tests-only" not in output and "public_key_pem" not in output
    assert main(["--config", str(path), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["phase"] == "active"
    namespaces("alpha").assert_scope()
    assert main(["--config", str(path), "rollback"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["historical_rows_preserved"] is True


@pytest.mark.parametrize(
    "problem", ["missing-token", "tenant-operator", "extra-field", "duplicate-json", "oversize", "missing-file"]
)
def test_cli_invalid_authority_or_configuration_is_generic(operator_config, authority, monkeypatch, capsys, problem):
    config, path = operator_config
    if problem == "missing-token":
        monkeypatch.delenv("AGENTBRIDGE_OPERATOR_TOKEN")
    elif problem == "tenant-operator":
        monkeypatch.setenv("AGENTBRIDGE_OPERATOR_TOKEN", authority[2]("administrator", tenant="alpha"))
    elif problem == "extra-field":
        config["secret-example"] = "must-not-appear"
        path.write_text(json.dumps(config), encoding="utf-8")
    elif problem == "duplicate-json":
        path.write_text('{"operator_issuer":"a","operator_issuer":"b"}', encoding="utf-8")
    elif problem == "oversize":
        path.write_bytes(b" " * 65537)
    else:
        path = path.with_name("missing-file.json")
    assert main(["--config", str(path), "freeze", "--tenant", "alpha"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "status": "denied",
        "error": "migration preconditions or operator authorization failed",
    }
    assert "must-not-appear" not in output and "postgresql" not in output
