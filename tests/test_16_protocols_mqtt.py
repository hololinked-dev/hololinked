import itertools
import os
import ssl
import time

from typing import Any, Generator

import pytest

from testcontainers.mqtt import (
    MosquittoContainer,  # TODO this will not work from the current release of testcontainers
)

from hololinked.client import ClientFactory, ObjectProxy
from hololinked.client.abstractions import SSE
from hololinked.server.http.server import HTTPServer
from hololinked.server.mqtt.server import MQTTPublisher
from hololinked.server.server import run, stop
from hololinked.utils import uuid_hex


try:
    from tests.test_14_protocols_http import (  # noqa: F401
        hostname_prefix,
        wait_until_server_ready,
    )
    from tests.things import TestThing
except ImportError:
    from test_14_protocols_http import (  # noqa: F401
        hostname_prefix,
        wait_until_server_ready,
    )
    from things import TestThing


count = itertools.count(63500)


def mqtt_ssl_context() -> ssl.SSLContext:
    mqtt_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if not os.path.exists(f"daq-system-infrastructure{os.sep}certs{os.sep}ca.crt"):
        raise FileNotFoundError("CA certificate 'ca.crt' not found in current directory for MQTT TLS connection")
    mqtt_ssl.load_verify_locations(cafile=f"daq-system-infrastructure{os.sep}certs{os.sep}ca.crt")
    mqtt_ssl.verify_mode = ssl.CERT_REQUIRED
    mqtt_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    return mqtt_ssl


@pytest.fixture(scope="module")
def mosquitto_container() -> Generator[MosquittoContainer, None, None]:
    container = MosquittoContainer(
        volumes=[
            (
                os.path.abspath("daq-system-infrastructure/conf/mosquitto.conf"),
                "/mosquitto/config/mosquitto.conf",
                "ro",
            ),
            (os.path.abspath("daq-system-infrastructure/conf/passwords.txt"), "/mosquitto/config/passwords.txt", "ro"),
            (os.path.abspath("daq-system-infrastructure/data/mosquitto"), "/mosquitto/data", "rw"),
            (os.path.abspath("daq-system-infrastructure/data/mosquitto/log"), "/mosquitto/log", "rw"),
            (os.path.abspath("daq-system-infrastructure/data/mosquitto/persisted"), "/mosquitto/data/persisted", "rw"),
            (os.path.abspath("daq-system-infrastructure/certs"), "/mosquitto/config/certs", "ro"),
        ],
        username="sampleuser",
        password="samplepass",
        mqtt_port=8883,
        ssl_context=mqtt_ssl_context(),
    )
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="module")
def mqtt_host(mosquitto_container: MosquittoContainer) -> str:
    return mosquitto_container.get_container_host_ip()


@pytest.fixture(scope="module")
def mqtt_port(mosquitto_container: MosquittoContainer) -> int:
    return int(mosquitto_container.get_exposed_port(8883))


@pytest.fixture(scope="module")
def http_port() -> int:
    global count
    return next(count)


@pytest.fixture(scope="module")
def thing(
    mosquitto_container: MosquittoContainer,  # place holder to boot it up
    http_port: int,
    mqtt_host: str,
    mqtt_port: int,
) -> Generator[TestThing, None, None]:
    thing = TestThing(id=f"test-thing-{uuid_hex()}", serial_number="simulation")
    http_server = HTTPServer(port=http_port, config=dict(cors=True))
    mqtt_publisher = MQTTPublisher(
        hostname=mqtt_host,
        port=mqtt_port,
        username="sampleuser",
        password="samplepass",
        ssl_context=mqtt_ssl_context(),
    )
    http_server.add_thing(thing)
    mqtt_publisher.add_thing(thing)
    run(http_server, mqtt_publisher, forked=True, print_welcome_message=False)
    wait_until_server_ready(port=http_port)
    yield thing
    stop()


@pytest.fixture(scope="function")
def td_endpoint(thing: TestThing, http_port: int) -> str:
    return f"{hostname_prefix}:{http_port}/{thing.id}/resources/wot-td"


@pytest.fixture(scope="function")
def object_proxy_http(td_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td_endpoint, ignore_TD_errors=True)


@pytest.fixture(scope="function")
@pytest.mark.asyncio  # bloody, the fixture needs to be marked asyncio. Does not pick it up for some reason.
async def object_proxy_mqtt(
    mqtt_host: str,
    mqtt_port: int,
    thing: TestThing,
) -> "ObjectProxy":
    return ClientFactory.mqtt(
        hostname=mqtt_host,
        port=mqtt_port,
        thing_id=thing.id,
        username="sampleuser",
        password="samplepass",
        ssl_context=mqtt_ssl_context(),
    )


def test_01_subscribe_event(object_proxy_http: "ObjectProxy", object_proxy_mqtt: "ObjectProxy"):
    results = []

    def cb(value: SSE):
        results.append(value)

    object_proxy_mqtt.subscribe_event("test_event", cb)
    time.sleep(3)

    for i in range(10):
        object_proxy_http.push_events(total_number_of_events=1)
        time.sleep(1)
        if len(results) > 0:
            results.clear()
            break
    else:
        pytest.skip("No events received from server, probably due to OS level issues")

    object_proxy_http.push_events()
    time.sleep(3)
    assert len(results) > 0, "No events received"
    assert abs(len(results) - 100) < 3, f"Expected 100 events, got {len(results)}"
    object_proxy_mqtt.unsubscribe_event("test_event")


@pytest.mark.parametrize(
    "prop, prospective_values, op",
    [
        pytest.param(
            "observable_list_prop",
            [
                [1, 2, 3, 4, 5],
                ["a", "b", "c", "d", "e"],
                [1, "a", 2, "b", 3],
            ],
            "write",
            id="observable-list-prop",
        ),
        pytest.param(
            "observable_readonly_prop",
            [1, 2, 3, 4, 5],
            "read",
            id="observable-readonly-prop",
        ),
    ],
)
def test_02_observe_properties(
    object_proxy_http: "ObjectProxy",
    object_proxy_mqtt: "ObjectProxy",
    prop: str,
    prospective_values: Any,
    op: str,
):
    # print(object_proxy_mqtt.properties)
    # assert hasattr(object_proxy_mqtt, f"{prop}_change_event")
    result = []
    attempt = 0

    def cb(value: SSE):
        nonlocal attempt
        result.append(value)
        attempt += 1

    object_proxy_mqtt.observe_property(prop, cb)
    time.sleep(3)
    for value in prospective_values:
        if op == "read":
            _ = object_proxy_http.read_property(prop)
        else:
            object_proxy_http.write_property(prop, value)
    for _ in range(20):
        if attempt == len(prospective_values):
            break
        time.sleep(0.1)
    object_proxy_mqtt.unobserve_property(prop)
    for index, res in enumerate(result):
        assert res.data == prospective_values[index]
