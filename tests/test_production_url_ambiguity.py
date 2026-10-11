"""Production URL parsing ambiguity regressions."""
import json
import pytest
from src.api.trusted_targets import resolve_target, SecurityConfigurationError


def config(url, proxy="http://egress.example.com:3128"):
    return {"AGENTBRIDGE_ENV": "production",
            "AGENTBRIDGE_EGRESS_PROXY_URL": proxy,
            "AGENTBRIDGE_TARGETS_JSON": json.dumps({"one": {
                "protocol": "a2a", "kind": "a2a_http",
                "capabilities": ["read"], "allowed_agents": ["agent"],
                "base_url": url}})}


@pytest.mark.parametrize("url", [
    "https://example.com:garbage",
    "https://example.com:99999",
    "https://example.com?destination=127.0.0.1",
    "https://example.com\\@127.0.0.1/",
    "https://example.com%2f.attacker.org/",
    "https://example.com./",
    "https://example.com:bad/path",
])
def test_ambiguous_urls_denied(url):
    with pytest.raises(SecurityConfigurationError):
        resolve_target("one", "a2a", "read", env=config(url), agent_id="agent")


@pytest.mark.parametrize("proxy", [
    "http://egress.example.com",
    "http://egress.example.com:bad",
    "http://egress.example.com:3128/route",
    "http://egress.example.com:3128?override=1",
    "http://user:pass@egress.example.com:3128",
])
def test_ambiguous_proxy_denied(proxy):
    with pytest.raises(SecurityConfigurationError):
        resolve_target("one", "a2a", "read",
                       env=config("https://example.com", proxy), agent_id="agent")


def test_valid_explicit_proxy_and_target():
    invocation = resolve_target("one", "a2a", "read",
                                env=config("https://example.com"), agent_id="agent")
    assert invocation["proxy_url"] == "http://egress.example.com:3128"
