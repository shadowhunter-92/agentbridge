"""Workload mTLS identity is pinned to independently enrolled certificate key."""
import datetime as dt
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID

from src.proxy.workload_identity import (
    WorkloadDenied,client_spki_sha256,parse_allowed_workload_spki,
    validate_workload,make_mtls_server_context,
)


def _cert(key, name):
    now=dt.datetime.now(dt.timezone.utc)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)])
    return (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(minutes=1))
            .not_valid_after(now+dt.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
            .sign(key,algorithm=None))


def test_pinned_mtls_key_and_untrusted_peer_denied(tmp_path):
    key=ed25519.Ed25519PrivateKey.generate()
    cert=_cert(key,"review-sandbox")
    der=cert.public_bytes(serialization.Encoding.DER)
    hashval=client_spki_sha256(der)
    class FakeTLS:
        def getpeercert(self,*,binary_form):
            assert binary_form
            return der
    class FakeWriter:
        def get_extra_info(self,name):
            return FakeTLS() if name=="ssl_object" else None
    assert validate_workload(FakeWriter(),frozenset({hashval}))==hashval
    with pytest.raises(WorkloadDenied):
        validate_workload(FakeWriter(),frozenset({"0"*64}))
    class Cleartext:
        def get_extra_info(self,name):
            return None
    with pytest.raises(WorkloadDenied):
        validate_workload(Cleartext(),frozenset({hashval}))
    assert parse_allowed_workload_spki(hashval)==frozenset({hashval})
    with pytest.raises(WorkloadDenied):
        parse_allowed_workload_spki("not-a-digest")


def test_server_ssl_context_requires_client_ca(tmp_path):
    key=ed25519.Ed25519PrivateKey.generate()
    cert=_cert(key,"review-ca")
    key_path=tmp_path/"key.pem";cert_path=tmp_path/"cert.pem"
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    context=make_mtls_server_context(
        certfile=str(cert_path),keyfile=str(key_path),trust_ca_file=str(cert_path))
    assert context.minimum_version==ssl.TLSVersion.TLSv1_3
    assert context.verify_mode==ssl.CERT_REQUIRED
