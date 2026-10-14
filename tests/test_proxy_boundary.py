"""Fail-closed destination policy and transport proxy contract (no network calls)."""
import inspect
import json
import pytest
from src.api.trusted_targets import resolve_target, SecurityConfigurationError
from src.proxy import transport


def _config(host, with_proxy=True):
    env={"AGENTBRIDGE_ENV":"production",
         "AGENTBRIDGE_TARGETS_JSON":json.dumps({
             "test":{"protocol":"a2a","capabilities":["read"],
                     "kind":"a2a_http","base_url":"https://"+host,
                     "allowed_agents":["reviewer"]}
         })}
    if with_proxy:
        env["AGENTBRIDGE_EGRESS_PROXY_URL"]="http://approved-egress.example.com:3128"
    return env


@pytest.mark.parametrize("host",["127.0.0.1","169.254.169.254","localhost",
                                     "service.internal","database.local","private.test"])
def test_private_or_ambiguous_production_destinations_rejected(host):
    with pytest.raises(SecurityConfigurationError):
        resolve_target("test","a2a","read",agent_id="reviewer",env=_config(host))


def test_no_egress_proxy_is_fail_closed():
    with pytest.raises(SecurityConfigurationError, match="outbound proxy"):
        resolve_target("test","a2a","read",agent_id="reviewer",
                       env=_config("service.example.com",with_proxy=False))


def test_transport_signatures_expose_operator_proxy_configuration():
    for method in (transport.fetch_a2a_card,transport.send_a2a_message,
                   transport.call_acp_agent):
        assert "proxy_url" in inspect.signature(method).parameters
    # A valid proxy does not qualify an opaque production destination.
    with pytest.raises(SecurityConfigurationError, match="destination-atomic"):
        resolve_target("test","a2a","read",agent_id="reviewer",
                       env=_config("service.example.com"))
