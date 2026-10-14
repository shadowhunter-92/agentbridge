"""Adversarial egress policies: DNS rebinding, mixed answers, CONNECT abuse."""
import socket
import pytest
from src.proxy.egress_policy import (
    EgressDenied, parse_allowed_hosts, parse_connect_target, resolve_global_addresses,
)


def test_connect_only_allows_explicit_tls_host():
    hosts = parse_allowed_hosts("api.example.com,service.example.org")
    assert parse_connect_target("api.example.com:443", hosts) == ("api.example.com", 443)
    for value in ("localhost:443", "127.0.0.1:443", "api.example.com:80",
                  "attacker.example:443", "api.example.com:443@evil.org",
                  "api.example.com.:443", "api.example.com:443/path",
                  "api.example.com:443\r\nInjected: yes",
                  "[::1]:443", "api.example.com:0443"):
        with pytest.raises(EgressDenied):
            parse_connect_target(value, hosts)


def test_all_answers_must_be_global():
    def responses(ips):
        return lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "",
             (ip, 443)) for ip in ips]
    assert resolve_global_addresses(
        "api.example.com", 443,
        getaddrinfo=responses(["8.8.8.8", "1.1.1.1"])) == ("8.8.8.8", "1.1.1.1")
    for addresses in (["8.8.8.8", "127.0.0.1"],
                      ["10.0.0.5"], ["169.254.169.254"],
                      ["192.168.1.10"], ["0.0.0.0"], ["192.0.2.11"]):
        with pytest.raises(EgressDenied):
            resolve_global_addresses("api.example.com", 443,
                                     getaddrinfo=responses(addresses))
    with pytest.raises(EgressDenied):
        resolve_global_addresses("api.example.com", 443, getaddrinfo=responses([]))
