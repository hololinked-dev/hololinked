import itertools

from typing import Generator

import pytest

from testcontainers.mqtt import (
    MosquittoContainer,  # TODO this will not work from the current release of testcontainers
)

from hololinked.client import ClientFactory, ObjectProxy
from hololinked.server.http.server import HTTPServer
from hololinked.server.mqtt.server import MQTTPublisher
from hololinked.server.server import run, stop
from hololinked.server.zmq.server import ZMQServer
from hololinked.utils import uuid_hex


try:
    from tests.test_14_protocols_http import wait_until_server_ready
    from tests.test_16_protocols_mqtt import (
        mosquitto_container,
        mqtt_host,
        mqtt_port,
        mqtt_ssl_context,
        td_endpoint,
    )
    from tests.things import OceanOpticsSpectrometer, TestThing
except ImportError:
    from test_14_protocols_http import wait_until_server_ready
    from test_16_protocols_mqtt import mqtt_ssl_context
    from things import OceanOpticsSpectrometer, TestThing

count = itertools.count(64000)


@pytest.fixture(scope="module")
def http_port() -> int:
    global count
    return next(count)


def zmq_tcp_port() -> int:
    global count
    return next(count)


@pytest.fixture(scope="module")
def things(
    mosquitto_container: MosquittoContainer,  # place holder to boot it up
    http_port: int,
    zmq_tcp_port: int,
    mqtt_host: str,
    mqtt_port: int,
) -> Generator[TestThing, None, None]:
    thing1 = TestThing(id=f"test-thing-{uuid_hex()}")
    thing2 = OceanOpticsSpectrometer(id=f"test-thing-{uuid_hex()}", serial_number="simulation")

    http_server = HTTPServer(port=http_port, config=dict(cors=True))
    zmq_server = ZMQServer(id="test-zmq-server", access_points=["IPC", f"tcp://*:{zmq_tcp_port()}"])

    mqtt_publisher = MQTTPublisher(
        hostname=mqtt_host,
        port=mqtt_port,
        username="sampleuser",
        password="samplepass",
        ssl_context=mqtt_ssl_context(),
    )
    http_server.add_thing(thing1)
    http_server.add_thing(thing2)
    mqtt_publisher.add_thing(thing1)
    mqtt_publisher.add_thing(thing2)
    zmq_server.add_thing(thing1)
    zmq_server.add_thing(thing2)

    run(http_server, mqtt_publisher, zmq_server, forked=True, print_welcome_message=False)
    wait_until_server_ready(port=http_port)
    yield thing1, thing2
    stop()


def object_proxy_http(td_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td_endpoint, ignore_TD_errors=True)


def object_proxy_mqtt(mqtt_host_and_port: tuple[str, int], mqtt_ssl_context) -> "ObjectProxy":
    mqtt_host, mqtt_port = mqtt_host_and_port
    return ClientFactory.mqtt(
        hostname=mqtt_host,
        port=mqtt_port,
        thing_id=thing.id,
        username="sampleuser",
        password="samplepass",
        ssl_context=mqtt_ssl_context(),
    )


def object_proxy_zmq(td_endpoint: str) -> "ObjectProxy":
    return ClientFactory.zmq(url=td_endpoint, ignore_TD_errors=True)


def test_01(
    object_proxy_http: "ObjectProxy",
    object_proxy_mqtt: "ObjectProxy",
    object_proxy_zmq: "ObjectProxy",
):
    pass
