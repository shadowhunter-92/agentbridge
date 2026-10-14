"""Actual TLS sockets enforce enrolled client-certificate workload identities."""
import asyncio
import datetime as dt
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID

from src.proxy.workload_identity import (
    client_spki_sha256,make_mtls_server_context,validate_workload,WorkloadDenied)


def _keypair():
    return ed25519.Ed25519PrivateKey.generate()


def _certificate(subject_key, name, issuer_key, issuer_name, *, ca=False):
    now=dt.datetime.now(dt.timezone.utc)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)])
    issuer=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,issuer_name)])
    b=(x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
       .public_key(subject_key.public_key()).serial_number(x509.random_serial_number())
       .not_valid_before(now-dt.timedelta(minutes=1))
       .not_valid_after(now+dt.timedelta(hours=1))
       .add_extension(x509.BasicConstraints(ca=ca,path_length=0 if ca else None),critical=True))
    return b.sign(issuer_key,algorithm=None)


def _write_key(path,key):
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))


def test_mtls_valid_client_and_unenrolled_client_over_real_tcp(tmp_path):
    ca_key=_keypair()
    ca=_certificate(ca_key,"ci-ca",ca_key,"ci-ca",ca=True)
    server_key=_keypair()
    server_cert=_certificate(server_key,"localhost",ca_key,"ci-ca")
    enrolled=_keypair()
    enrolled_cert=_certificate(enrolled,"enrolled",ca_key,"ci-ca")
    other=_keypair()
    other_cert=_certificate(other,"other",ca_key,"ci-ca")
    ca_file=tmp_path/"ca.pem"
    server_file=tmp_path/"server.pem"
    server_key_file=tmp_path/"server.key"
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    server_file.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    _write_key(server_key_file,server_key)
    server_context=make_mtls_server_context(
        certfile=str(server_file),keyfile=str(server_key_file),
        trust_ca_file=str(ca_file))
    allowed=frozenset({client_spki_sha256(enrolled_cert.public_bytes(
        serialization.Encoding.DER))})

    async def exercise():
        async def handler(reader,writer):
            try:
                validate_workload(writer,allowed)
                writer.write(b"AUTHORIZED")
            except WorkloadDenied:
                writer.write(b"DENIED")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server=await asyncio.start_server(handler,"127.0.0.1",0,ssl=server_context)
        port=server.sockets[0].getsockname()[1]
        try:
            async def client(key,cert):
                certfile=tmp_path/(cert.subject.rfc4514_string().replace("=","-")+".pem")
                keyfile=tmp_path/(cert.subject.rfc4514_string().replace("=","-")+".key")
                certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                _write_key(keyfile,key)
                ctx=ssl.create_default_context(cafile=str(ca_file))
                ctx.minimum_version=ssl.TLSVersion.TLSv1_3
                ctx.load_cert_chain(str(certfile),str(keyfile))
                reader,writer=await asyncio.open_connection(
                    "127.0.0.1",port,ssl=ctx,server_hostname="localhost")
                result=await asyncio.wait_for(reader.read(32),5)
                writer.close()
                await writer.wait_closed()
                return result
            assert await client(enrolled,enrolled_cert)==b"AUTHORIZED"
            assert await client(other,other_cert)==b"DENIED"
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(exercise())
