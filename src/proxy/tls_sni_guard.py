"""Strict, bounded TLS ClientHello SNI parser for a CONNECT-only guard.

Only a single complete TLS ClientHello record with exactly one DNS SNI is
accepted. Unknown/fragmented/ECH offers fail closed. This prevents ordinary
CONNECT-host versus ClientHello-SNI mismatch, but it is NOT an authenticated
end-to-end TLS upstream identity check or a production proxy certification.
"""
from __future__ import annotations


class InvalidClientHello(ValueError):
    pass


def _segment(data: bytes, start: int, width: int):
    end = start + width
    if width < 0 or end > len(data):
        raise InvalidClientHello("truncated TLS structure")
    return data[start:end], end


def parse_tls_client_hello_sni(record: bytes) -> str:
    if not isinstance(record, bytes) or len(record) < 9 or len(record) > 16389:
        raise InvalidClientHello("bounded TLS ClientHello record required")
    if record[0] != 22 or record[1] != 3 or record[2] not in (1, 2, 3, 4):
        raise InvalidClientHello("CONNECT payload must begin with TLS handshake")
    length = int.from_bytes(record[3:5], "big")
    if length != len(record) - 5 or length > 16384:
        raise InvalidClientHello("TLS record length invalid")
    body = record[5:]
    if body[0] != 1 or int.from_bytes(body[1:4], "big") != len(body) - 4:
        raise InvalidClientHello("expected one complete ClientHello")
    p = 4
    _, p = _segment(body, p, 2 + 32)  # legacy version and random
    session_size, p = _segment(body, p, 1)
    _, p = _segment(body, p, session_size[0])
    cipher_bytes, p = _segment(body, p, 2)
    cipher_size = int.from_bytes(cipher_bytes, "big")
    if cipher_size == 0 or cipher_size % 2:
        raise InvalidClientHello("invalid cipher suite block")
    _, p = _segment(body, p, cipher_size)
    compression_bytes, p = _segment(body, p, 1)
    if not compression_bytes[0]:
        raise InvalidClientHello("no compression method")
    _, p = _segment(body, p, compression_bytes[0])
    extensions_len, p = _segment(body, p, 2)
    ext_size = int.from_bytes(extensions_len, "big")
    if ext_size == 0 or p + ext_size != len(body):
        raise InvalidClientHello("extension structure invalid")
    found = None
    end = len(body)
    seen = set()
    while p < end:
        header, p = _segment(body, p, 4)
        typ, n = int.from_bytes(header[:2], "big"), int.from_bytes(header[2:], "big")
        if typ in seen:
            raise InvalidClientHello("duplicate TLS extension")
        seen.add(typ)
        value, p = _segment(body, p, n)
        if typ == 0xfe0d:  # encrypted_client_hello (ECH)
            raise InvalidClientHello("ECH cannot be inspected by this proxy")
        if typ == 0:
            if len(value) < 5 or int.from_bytes(value[:2], "big") != len(value) - 2:
                raise InvalidClientHello("invalid SNI list")
            if value[2] != 0:
                raise InvalidClientHello("SNI entry must be DNS hostname")
            hostname_size = int.from_bytes(value[3:5], "big")
            if hostname_size != len(value) - 5:
                raise InvalidClientHello("multiple or invalid SNI identities")
            try:
                found = value[5:].decode("ascii").lower()
            except UnicodeError as exc:
                raise InvalidClientHello("non-ASCII TLS SNI") from exc
    if not found or p != end:
        raise InvalidClientHello("one unencrypted DNS SNI is required")
    from .egress_policy import _valid_dns_name
    if not _valid_dns_name(found):
        raise InvalidClientHello("TLS SNI is not a valid DNS hostname")
    return found
