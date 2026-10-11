"""Fail-closed production configuration regression tests."""
import pytest
from src.config import validate_config, ConfigError


def _base(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    monkeypatch.setenv("AGENTBRIDGE_ADMIN_KEY", "x" * 40)
    monkeypatch.setenv("AGENTBRIDGE_DB", "test-production.db")
    monkeypatch.delenv("AGENTBRIDGE_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", raising=False)
    monkeypatch.delenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", raising=False)


def test_partial_readback_keys_fail_startup(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", "a" * 64)
    with pytest.raises(ConfigError):
        validate_config()


def test_readback_signer_must_be_separate(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", "a" * 64)
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", "A" * 64)
    with pytest.raises(ConfigError):
        validate_config()


def test_nan_operational_settings_fail_startup(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AGENTBRIDGE_SLOW_LOG_SECONDS", "nan")
    with pytest.raises(ConfigError):
        validate_config()
    monkeypatch.setenv("AGENTBRIDGE_SLOW_LOG_SECONDS", "2.0")
    monkeypatch.setenv("AGENTBRIDGE_SHUTDOWN_GRACE", "inf")
    with pytest.raises(ConfigError):
        validate_config()


def test_valid_independent_keys_accepted(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_DESTINATION_KEY_HEX", "a" * 64)
    monkeypatch.setenv("AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX", "b" * 64)
    assert not [item for item in validate_config() if item.severity == "error"]
