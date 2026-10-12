"""Strict CONNECT destination policy for an isolated outbound proxy.

A trusted proxy must resolve DNS and connect to the *verified numeric address*,
without performing a second name lookup after policy evaluation. Merely checking
the spelling of the hostname is not an SSRF/DNS-rebinding defense.
"""
from __future__ import annotations

import ipaddress
import socket


class EgressDenied(ValueError):
    """The outbound destination cannot be safely authorized."""


def parse_allowed_hosts(raw: str) -> frozenset[str]:
    if not isinstance(raw, str):
        raise EgressDenied("explicit egress host allowlist required")
    hosts = raw.split(",")
    if not 1 <= len(hosts) <= 100:
        raise EgressDenied("egress host allowlist must contain 1-100 entries")
    normalized = set()
    for name in hosts:
        if name != name.strip() or not _valid_dns_name(name):
            raise EgressDenied("egress allowlist must contain exact public DNS hostnames")
        normalized.add(name.lower())
    if len(normalized) != len(hosts):
        raise EgressDenied("duplicate egress hostnames")
    return frozenset(normalized)


def _valid_dns_name(host: str) -> bool:
    if not isinstance(host, str) or not 4 <= len(host) <= 253:
        return False
    if not host.isascii() or host.lower() != host and host.upper() != host:
        # Mixed-case names are valid DNS, but all characters are still validated below.
        pass
    if host.endswith(".") or host.startswith(".") or ".." in host:
        return False
    labels = host.split(".")
    if len(labels) < 2 or labels[-1].lower() in ("local", "internal", "test", "localhost"):
        return False
    for label in labels:
        if not 1 <= len(label) <= 63 or label[0] == "-" or label[-1] == "-":
            return False
        if not all(c.isascii() and (c.isalnum() or c == "-") for c in label):
            return False
    if labels[-1].isdigit():
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


def parse_connect_target(authority: str, allowed_hosts: frozenset[str]) -> tuple[str, int]:
    """Allow only exact allowlisted hostname:443 CONNECT authorities."""
    if (not isinstance(authority, str) or not authority.isascii()
            or authority.count(":") != 1 or any(c in authority for c in "/\\@%?# \t\r\n")):
        raise EgressDenied("invalid CONNECT authority")
    host, raw_port = authority.rsplit(":", 1)
    if not _valid_dns_name(host) or raw_port != "443":
        raise EgressDenied("CONNECT requires a public DNS name and TLS port 443")
    host = host.lower()
    if host not in allowed_hosts:
        raise EgressDenied("CONNECT host is not allowlisted")
    return host, 443


def resolve_global_addresses(host: str, port: int, *, getaddrinfo=None) -> tuple[str, ...]:
    """Reject *all* mixed public/private DNS answers and pin approved numeric IPs."""
    lookup = socket.getaddrinfo if getaddrinfo is None else getaddrinfo
    try:
        results = lookup(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise EgressDenied("destination DNS lookup failed") from exc
    if not results:
        raise EgressDenied("destination has no DNS results")
    addresses = []
    for family, socktype, proto, canon, sockaddr in results:
        if family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_STREAM:
            raise EgressDenied("unsupported DNS answer family or socket type")
        try:
            parsed = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise EgressDenied("unrecognized destination address") from exc
        if not parsed.is_global:
            raise EgressDenied("DNS answer includes nonpublic or reserved address")
        if str(parsed) not in addresses:
            addresses.append(str(parsed))
    return tuple(addresses)
