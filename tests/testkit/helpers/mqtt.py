import ssl

from pathlib import Path


MQTT_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "mqtt"
"""Broker config, plus the certs and password file CI decodes from its secret"""


def mqtt_ssl_context() -> ssl.SSLContext:
    mqtt_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    cafile = MQTT_ASSETS / "certs" / "ca.crt"
    if not cafile.exists():
        raise FileNotFoundError(f"CA certificate not found at {cafile} for MQTT TLS connection")
    mqtt_ssl.load_verify_locations(cafile=cafile)
    mqtt_ssl.verify_mode = ssl.CERT_REQUIRED
    mqtt_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    return mqtt_ssl
