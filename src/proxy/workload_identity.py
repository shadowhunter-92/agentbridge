"""mTLS workload identity gate for isolated egress review deployments.

Server TLS requires a separately provisioned CA and client certificate. The
client's SPKI SHA256 must appear in an explicit administrator-owned allowlist;
TLS CA trust alone does not authorize access to consequential destinations.
This is a component and CI reference, not a reviewed production ingress.
"""
import hashlib
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import serialization


class WorkloadDenied(ValueError):
    pass


def client_spki_sha256(der_cert):
    if not isinstance(der_cert, bytes) or not der_cert:
        raise WorkloadDenied("mTLS client certificate required")
    try:
        cert=x509.load_der_x509_certificate(der_cert)
        spki=cert.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
    except Exception as exc:
        raise WorkloadDenied("invalid mTLS client certificate") from exc
    return hashlib.sha256(spki).hexdigest()


def validate_workload(writer, allowed_spki):
    if not isinstance(allowed_spki, frozenset) or not allowed_spki:
        raise WorkloadDenied("explicit mTLS workload allowlist required")
    sock=writer.get_extra_info("ssl_object")
    if sock is None:
        raise WorkloadDenied("TLS client authentication required")
    digest=client_spki_sha256(sock.getpeercert(binary_form=True))
    if digest not in allowed_spki:
        raise WorkloadDenied("unrecognized workload identity")
    return digest


def make_mtls_server_context(*,certfile,keyfile,trust_ca_file):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_3
    context.verify_mode=ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=trust_ca_file)
    context.load_cert_chain(certfile=certfile,keyfile=keyfile)
    return context


def parse_allowed_workload_spki(raw):
    if not isinstance(raw,str):
        raise WorkloadDenied("mTLS workload identities required")
    values=raw.split(",")
    if not 1<=len(values)<=100:
        raise WorkloadDenied("invalid workload allowlist cardinality")
    if any(len(x)!=64 or any(c not in "0123456789abcdef" for c in x) for x in values):
        raise WorkloadDenied("malformed workload key hash")
    if len(set(values))!=len(values):
        raise WorkloadDenied("duplicate workload identity")
    return frozenset(values)
