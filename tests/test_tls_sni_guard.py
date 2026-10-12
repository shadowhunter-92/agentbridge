"""TLS SNI guard: exact hostname, malformed records and ECH fail closed."""
import pytest
from src.proxy.tls_sni_guard import InvalidClientHello, parse_tls_client_hello_sni


def hello(host="api.example.com", *, ech=False):
    name=host.encode("ascii")
    sni=b"\x00"+len(name).to_bytes(2,"big")+name
    sni_data=len(sni).to_bytes(2,"big")+sni
    extension=b"\x00\x00"+len(sni_data).to_bytes(2,"big")+sni_data
    if ech:
        extension+=b"\xfe\x0d\x00\x01\x00"
    payload=(b"\x03\x03"+bytes(32)+b"\x00"+
             b"\x00\x02\x13\x01"+b"\x01\x00"+
             len(extension).to_bytes(2,"big")+extension)
    handshake=b"\x01"+len(payload).to_bytes(3,"big")+payload
    return b"\x16\x03\x03"+len(handshake).to_bytes(2,"big")+handshake


def test_sni_parses_expected_dns_host():
    assert parse_tls_client_hello_sni(hello())=="api.example.com"


@pytest.mark.parametrize("value",[
    b"",b"GET / HTTP/1.1",hello()[:-1],hello("localhost"),
    hello(ech=True),hello()+b"junk",
])
def test_bad_hello_fails_closed(value):
    with pytest.raises(InvalidClientHello):
        parse_tls_client_hello_sni(value)


def test_sni_is_not_connect_host():
    assert parse_tls_client_hello_sni(hello("evil.example.org"))!="api.example.com"
