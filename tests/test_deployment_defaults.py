"""Runnable configurations must require secrets and identify actual consumers."""

from pathlib import Path

import pytest
import yaml

from src.config import ConfigError, validate_config

ROOT = Path(__file__).resolve().parents[1]


def test_runnable_local_compose_requires_secret_and_binds_loopback():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["agentbridge"]
    assert service["ports"] == ["127.0.0.1:8000:8000"]
    assert any("AGENTBRIDGE_ADMIN_KEY=${AGENTBRIDGE_ADMIN_KEY:?" in item for item in service["environment"])


def test_kubernetes_secret_is_provisioned_separately_and_readiness_is_ready():
    manifests = [m for m in yaml.safe_load_all((ROOT / "k8s/deployment.yaml").read_text()) if m]
    assert not any(m["kind"] == "Secret" for m in manifests)
    deployment = next(m for m in manifests if m["kind"] == "Deployment")
    assert deployment["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]["httpGet"]["path"] == "/ready"


@pytest.mark.parametrize("key", ["change-me-in-production", "changeme", "password", "admin"])
def test_known_administrator_placeholders_fail_in_every_mode(monkeypatch, key):
    monkeypatch.setenv("AGENTBRIDGE_ADMIN_KEY", key)
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    with pytest.raises(ConfigError):
        validate_config()


def test_docker_publication_selects_runtime_review_recipe():
    workflow = yaml.safe_load((ROOT / ".github/workflows/docker-publish.yml").read_text())
    push = next(step for step in workflow["jobs"]["docker"]["steps"] if "docker/build-push-action" in step.get("uses", ""))
    assert push["with"]["file"] == "Dockerfile.release"


def test_registry_publication_requires_explicit_owner_gate():
    for filename, job in (("publish.yml", "publish"), ("docker-publish.yml", "docker")):
        workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
        assert "AGENTBRIDGE_PUBLISH_APPROVED" in workflow["jobs"][job]["if"]
        assert workflow["jobs"][job]["environment"] in ("pypi-release", "container-release")


def test_missing_live_transport_sdk_fails_at_startup(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_TARGETS_JSON", '{"synthetic":{"kind":"mcp_stdio"}}')
    monkeypatch.setenv("AGENTBRIDGE_ADMIN_KEY", "test-admin-key")
    monkeypatch.setattr("src.config.importlib.util.find_spec", lambda name: None)
    with pytest.raises(ConfigError):
        validate_config()
