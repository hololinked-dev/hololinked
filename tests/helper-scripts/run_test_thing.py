import argparse
import json
import os
import ssl
import sys
import time

import structlog


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from things import OceanOpticsSpectrometer, TestThing

from hololinked.config import global_config
from hololinked.serializers import Serializers
from hololinked.server import run, stop
from hololinked.server.http import HTTPServer
from hololinked.server.mqtt import MQTTPublisher
from hololinked.server.security import Argon2BasicSecurity, BcryptBasicSecurity, OIDCSecurity
from hololinked.server.zmq import ZMQServer


logger = structlog.get_logger()


def parse_args():
    parser = argparse.ArgumentParser(description="Run test things with configurable servers and security")

    parser.add_argument(
        "--servers",
        type=str,
        default="http",
        help="Comma-separated list of servers to run (http, zmq, mqtt). Default: http",
    )
    parser.add_argument(
        "--security",
        type=str,
        default="",
        help="Comma-separated list of security schemes to use (bcrypt, oidc). Default: none",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=8080,
        help="HTTP server port. Default: 8080",
    )
    parser.add_argument(
        "--mqtt-hostname",
        type=str,
        default="localhost",
        help="MQTT broker hostname. Default: localhost",
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=8883,
        help="MQTT broker port. Default: 8883",
    )
    parser.add_argument(
        "--mqtt-username",
        type=str,
        default="sampleuser",
        help="MQTT username. Default: sampleuser",
    )
    parser.add_argument(
        "--mqtt-password",
        type=str,
        default="samplepass",
        help="MQTT password. Default: samplepass",
    )
    parser.add_argument(
        "--mqtt-qos",
        type=int,
        default=1,
        help="MQTT QoS level. Default: 1",
    )
    parser.add_argument(
        "--mqtt-ca-cert",
        type=str,
        default="ca.crt",
        help="MQTT CA certificate file path. Default: ca.crt",
    )

    parser.add_argument(
        "--seconds",
        type=int,
        default=-1,
        help="Number of seconds to run. Default: -1 (run indefinitely)",
    )

    parser.add_argument(
        "--forked",
        action="store_true",
        help="Run servers in forked mode",
    )

    parser.add_argument(
        "--username",
        type=str,
        default="testuser",
        help="Username for basic security. Default: testuser",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="samplepass",
        help="Password for basic security. Default: samplepass",
    )

    parser.add_argument(
        "--cors",
        action="store_true",
        default=True,
        help="Enable CORS for HTTP server. Default: True",
    )

    return parser.parse_args()


# keycloak_security = OIDCSecurity(
#     issuer="http://localhost:8080/realms/example-realm",
#     audience="device-server",
# )

oidc_config = json.loads(open("oidc-config.json").read())
ory_security = OIDCSecurity(
    issuer=oidc_config["issuer"],
    audience=oidc_config["audience"],
)


def setup_security_schemes(security_names, args):
    """Setup security schemes based on command line arguments"""
    security_schemes = []

    if not security_names:
        return security_schemes

    for name in security_names:
        name = name.strip().lower()
        if name == "bcrypt":
            bcrypt_security = BcryptBasicSecurity(username=args.username, password=args.password)
            security_schemes.append(bcrypt_security)
            logger.info("Added Bcrypt security scheme")
        elif name == "argon2":
            argon2_security = Argon2BasicSecurity(username=args.username, password=args.password)
            security_schemes.append(argon2_security)
            logger.info("Added Argon2 security scheme")
        elif name == "oidc":
            oidc_security = ory_security
            security_schemes.append(oidc_security)
            logger.info("Added OIDC security scheme")
        else:
            logger.info(f"Unknown security scheme: {name}")

    return security_schemes


def setup_servers(server_names, args, security_schemes):
    """Setup servers based on command line arguments"""
    servers = []

    for name in server_names:
        name = name.strip().lower()
        if name == "http":
            http_server = HTTPServer(
                port=args.http_port,
                config=dict(cors=args.cors),
                security_schemes=security_schemes if security_schemes else None,
            )
            servers.append(http_server)
            logger.info(f"Added HTTP server on port {args.http_port}")
        elif name == "zmq":
            zmq_server = ZMQServer(id="example-test-server", access_points="IPC")
            servers.append(zmq_server)
            logger.info("Added ZMQ server with IPC access")
        elif name == "mqtt":
            mqtt_ssl = None
            if os.path.exists(args.mqtt_ca_cert):
                mqtt_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                mqtt_ssl.load_verify_locations(cafile=args.mqtt_ca_cert)
                mqtt_ssl.check_hostname = True
                mqtt_ssl.verify_mode = ssl.CERT_REQUIRED
                mqtt_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
                logger.info(f"MQTT: Using TLS with CA cert: {args.mqtt_ca_cert}")
            else:
                logger.info(f"MQTT: CA certificate '{args.mqtt_ca_cert}' not found, proceeding without TLS")

            mqtt_publisher = MQTTPublisher(
                hostname=args.mqtt_hostname,
                port=args.mqtt_port,
                username=args.mqtt_username,
                password=args.mqtt_password,
                qos=args.mqtt_qos,
                ssl_context=mqtt_ssl,
            )
            servers.append(mqtt_publisher)
            logger.info(f"Added MQTT publisher to {args.mqtt_hostname}:{args.mqtt_port}")
        else:
            logger.info(f"Unknown server type: {name}")

    return servers


def main():
    args = parse_args()

    # Setup global config
    global_config.DEBUG = True
    global_config.USE_LOG_FILE = True
    global_config.setup()

    # Parse server and security names
    server_names = [s.strip() for s in args.servers.split(",") if s.strip()]
    security_names = [s.strip() for s in args.security.split(",") if s.strip()]

    logger.info(f"Requested servers: {server_names}")
    logger.info(f"Requested security schemes: {security_names}")

    # Setup security schemes
    security_schemes = setup_security_schemes(security_names, args)

    # Setup servers
    servers = setup_servers(server_names, args, security_schemes)

    # Instantiate things
    thing1 = TestThing(id="test-thing")
    thing2 = OceanOpticsSpectrometer(id="test-spectrometer", serial_number="simulation")

    # Register serializers
    Serializers.register_for_object(TestThing.db_init_int_prop, Serializers.pickle)
    Serializers.register_for_object(TestThing.set_non_remote_number_prop, Serializers.msgpack)
    Serializers.register_for_object(TestThing.get_non_remote_number_prop, Serializers.msgpack)
    Serializers.register_for_object(TestThing.numpy_array_prop, Serializers.msgpack)
    Serializers.register_for_object(TestThing.numpy_action, Serializers.msgpack)

    if not servers:
        logger.error("No valid servers configured. Exiting.")
        return

    # Add things to servers
    for server in servers:
        server_type = type(server).__name__
        if server_type == "HTTPServer":
            server.add_things(thing1)
            logger.info("Added thing1 to HTTP server")
        elif server_type == "ZMQServer":
            server.add_things(thing1, thing2)
            logger.info("Added thing1 and thing2 to ZMQ server")
        elif server_type == "MQTTPublisher":
            server.add_things(thing2)
            logger.info("Added thing2 to MQTT publisher")

    # Run servers
    logger.info(f"Starting {len(servers)} server(s) (forked={args.forked})...")
    run(*servers, forked=args.forked)

    # Main thread loop
    for i in range(args.iterations):
        logger.info(f"Running main thread iteration {i}")
        time.sleep(1)

    # Stop servers
    stop()
    logger.info("Servers shut down successfully.")


if __name__ == "__main__":
    main()
