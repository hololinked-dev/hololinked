import os
import ssl


def mqtt_ssl_context() -> ssl.SSLContext:
    mqtt_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if not os.path.exists(f"daq-system-infrastructure{os.sep}certs{os.sep}ca.crt"):
        raise FileNotFoundError("CA certificate 'ca.crt' not found in current directory for MQTT TLS connection")
    mqtt_ssl.load_verify_locations(cafile=f"daq-system-infrastructure{os.sep}certs{os.sep}ca.crt")
    mqtt_ssl.verify_mode = ssl.CERT_REQUIRED
    mqtt_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    return mqtt_ssl
