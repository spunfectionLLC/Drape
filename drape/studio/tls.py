"""A self-signed certificate so a shared studio can be served over https.

Browsers only allow WebGPU (live mode) on secure pages: https, or the computer
the server runs on. On a home network there is no real certificate to be had,
so drape makes its own, once, and keeps it in ~/.drape/tls. The other device's
browser warns about it the first time ("not private"); after the person
chooses to continue, the page counts as secure and live mode works.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
from pathlib import Path


def cert_dir() -> Path:
    return Path(os.environ.get("DRAPE_TLS_DIR", Path.home() / ".drape" / "tls"))


def _covers(cert_pem: bytes, ips: list[str]) -> bool:
    from cryptography import x509
    c = x509.load_pem_x509_certificate(cert_pem)
    if c.not_valid_after_utc < dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7):
        return False
    try:
        san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    have = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    return all(ip in have for ip in ips)


def ensure_cert(ips: list[str]) -> tuple[Path, Path]:
    """(cert.pem, key.pem) valid for localhost and the given IP addresses; made once,
    remade if this computer's network address changed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    d = cert_dir()
    d.mkdir(parents=True, exist_ok=True)
    cp, kp = d / "cert.pem", d / "key.pem"
    ips = sorted({"127.0.0.1", *[i for i in ips if i]})
    if cp.exists() and kp.exists() and _covers(cp.read_bytes(), ips):
        return cp, kp
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Spunfection Studio (this computer)")])
    now = dt.datetime.now(dt.timezone.utc)
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=730))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    os.chmod(kp, 0o600)
    cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cp, kp


def https_server(server_cls, addr, handler, ips: list[str]):
    """An http.server that speaks https with drape's own certificate.

    The TLS handshake happens in each connection's own thread (with a timeout),
    not in the accept loop: browsers open spare connections ahead of time and may
    leave one idle, which would otherwise freeze every request behind it (the
    page loads, its stylesheet and scripts never do)."""
    import socket
    import ssl
    cp, kp = ensure_cert(ips)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cp, kp)

    class TLSServer(server_cls):
        def finish_request(self, request, client_address):     # runs in the connection's thread
            request.settimeout(20)
            try:
                tls = ctx.wrap_socket(request, server_side=True)
            except (ssl.SSLError, OSError, socket.timeout):
                return          # a refused certificate, an idle spare connection, a port scan
            try:
                tls.settimeout(None)
                self.RequestHandlerClass(tls, client_address, self)
            finally:
                try:
                    tls.close()
                except OSError:
                    pass

        def handle_error(self, request, client_address):     # dropped connections are routine here
            import sys
            if not isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, socket.timeout)):
                super().handle_error(request, client_address)

    return TLSServer(addr, handler)
