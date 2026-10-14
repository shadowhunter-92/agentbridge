"""DNS policy IPv6 and ambiguous address regressions."""
import socket
import pytest
from src.proxy.egress_policy import EgressDenied, resolve_global_addresses, parse_connect_target


def test_ipv6_dns_answers_reject_private_link_local_and_mixed():
    def ips(*values):
        return lambda *args, **kwargs: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, 443, 0, 0))
            for addr in values
        ]
    for answers in (
        ("::1",), ("fe80::1",), ("fc00::1",), ("::ffff:127.0.0.1",),
        ("2001:4860:4860::8888", "::1"),
    ):
        with pytest.raises(EgressDenied):
            resolve_global_addresses("api.example.com", 443, getaddrinfo=ips(*answers))
    assert resolve_global_addresses(
        "api.example.com", 443,
        getaddrinfo=ips("2001:4860:4860::8888")) == ("2001:4860:4860::8888",)


def test_connect_does_not_accept_ipv6_literal_or_percent_encoded_authority():
    allow = frozenset({"api.example.com"})
    for value in ("[::1]:443", "fe80::1:443", "api.example.com%00:443",
                  "api.example.com:443%0d", "api.example.com:443?x=1"):
        with pytest.raises(EgressDenied):
            parse_connect_target(value, allow)
