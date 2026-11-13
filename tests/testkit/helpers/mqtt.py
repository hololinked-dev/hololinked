import base64
import hashlib
import ipaddress
import os
import ssl

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


NO_KEY_USAGE = dict(
    digital_signature=False,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=False,
    crl_sign=False,
    encipher_only=False,
    decipher_only=False,
)
"""every flag of `x509.KeyUsage` unset, override the ones a certificate needs"""


def generate_mqtt_credentials(
    directory: Path,
    username: str = "sampleuser",
    password: str = "samplepass",
    hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1"),
) -> Path:
    """
    Write a CA, a server certificate for `hosts` and a password file in the layout mosquitto.conf expects.

    Creates `certs/ca.crt`, `certs/server.crt`, `certs/server.key` and `passwords.txt` under `directory`,
    all readable by the mosquitto user of the container they are bind mounted into. Valid for a day.
    """
    certs = directory / "certs"
    certs.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    not_before, not_after = now - timedelta(minutes=5), now + timedelta(days=1)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hololinked MQTT test CA")])
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(**{**NO_KEY_USAGE, "key_cert_sign": True, "crl_sign": True}), critical=True)
        .add_extension(ca_ski, critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = ec.generate_private_key(ec.SECP256R1())
    alt_names = []
    for host in hosts:
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            alt_names.append(x509.DNSName(host))
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(**{**NO_KEY_USAGE, "digital_signature": True}), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    (certs / "ca.crt").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (certs / "server.crt").write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    (certs / "server.key").write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (directory / "passwords.txt").write_text(f"{username}:{mosquitto_password_hash(password)}\n")

    # bind mounted read-only, so the container cannot chown them to its mosquitto user
    os.chmod(certs, 0o755)
    for file in [*certs.iterdir(), directory / "passwords.txt"]:
        os.chmod(file, 0o644)
    return directory


def mosquitto_password_hash(password: str, iterations: int = 101) -> str:
    """the `$7$` (PBKDF2-SHA512) format of mosquitto_passwd"""
    salt = os.urandom(12)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, iterations, dklen=64)
    return f"$7${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def generate_mqtt_ssl_context(cafile: Path) -> ssl.SSLContext:
    mqtt_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    mqtt_ssl.load_verify_locations(cafile=cafile)
    mqtt_ssl.verify_mode = ssl.CERT_REQUIRED
    mqtt_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    return mqtt_ssl
