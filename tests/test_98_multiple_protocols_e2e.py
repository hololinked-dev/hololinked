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
    )
    from tests.things import OceanOpticsSpectrometer, TestThing
except ImportError:
    from test_14_protocols_http import wait_until_server_ready
    from test_16_protocols_mqtt import mosquitto_container, mqtt_host, mqtt_port, mqtt_ssl_context  # noqa: F401
    from things import OceanOpticsSpectrometer, TestThing

count = itertools.count(64000)


@pytest.fixture(scope="module")
def http_port() -> int:
    global count
    return next(count)


@pytest.fixture(scope="module")
def zmq_tcp_port() -> int:
    global count
    return next(count)


@pytest.fixture(scope="module")
def thing1() -> TestThing:
    return TestThing(id=f"test-thing-{uuid_hex()}")


@pytest.fixture(scope="module")
def thing2() -> OceanOpticsSpectrometer:
    return OceanOpticsSpectrometer(id=f"test-thing-{uuid_hex()}", serial_number="simulation")


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def things(
    mosquitto_container: MosquittoContainer,  # place holder to boot it up
    thing1: TestThing,
    thing2: OceanOpticsSpectrometer,
    http_port: int,
    zmq_tcp_port: int,
    mqtt_host: str,
    mqtt_port: int,
) -> Generator[TestThing, None, None]:
    http_server = HTTPServer(port=http_port, config=dict(cors=True))
    zmq_server = ZMQServer(id="test-zmq-server", access_points=["IPC", f"tcp://*:{zmq_tcp_port}"])

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

    run(http_server, mqtt_publisher, zmq_server, forked=True)
    wait_until_server_ready(port=http_port)
    yield thing1, thing2
    stop()


hostname_prefix = "http://127.0.0.1"


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def td1_endpoint(things: tuple[TestThing, OceanOpticsSpectrometer], http_port: int) -> str:
    thing1, _ = things
    return f"{hostname_prefix}:{http_port}/{thing1.id}/resources/wot-td"


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def td2_endpoint(things: tuple[TestThing, OceanOpticsSpectrometer], http_port: int) -> str:
    _, thing2 = things
    return f"{hostname_prefix}:{http_port}/{thing2.id}/resources/wot-td"


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def object_proxy_thing1_http(td1_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td1_endpoint, ignore_TD_errors=True)


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def object_proxy_thing2_http(td2_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td2_endpoint, ignore_TD_errors=True)


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def object_proxy_thing1_mqtt(
    mqtt_host: str,
    mqtt_port: int,
    things: tuple[TestThing, OceanOpticsSpectrometer],
) -> "ObjectProxy":
    thing1, _ = things
    return ClientFactory.mqtt(
        hostname=mqtt_host,
        port=mqtt_port,
        thing_id=thing1.id,
        username="sampleuser",
        password="samplepass",
        ssl_context=mqtt_ssl_context(),
    )


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def object_proxy_thing2_mqtt(
    mqtt_host: str,
    mqtt_port: int,
    things: tuple[TestThing, OceanOpticsSpectrometer],
) -> "ObjectProxy":
    _, thing2 = things
    return ClientFactory.mqtt(
        hostname=mqtt_host,
        port=mqtt_port,
        thing_id=thing2.id,
        username="sampleuser",
        password="samplepass",
        ssl_context=mqtt_ssl_context(),
    )


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def object_proxy_thing1_zmq(things: tuple[TestThing, OceanOpticsSpectrometer]) -> "ObjectProxy":
    thing1, _ = things
    return ClientFactory.zmq(
        access_point="IPC",
        thing_id=thing1.id,
        server_id="test-zmq-server",
        ignore_TD_errors=True,
    )


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def object_proxy_thing2_zmq(things: tuple[TestThing, OceanOpticsSpectrometer]) -> "ObjectProxy":
    _, thing2 = things
    return ClientFactory.zmq(
        access_point="IPC",
        thing_id=thing2.id,
        server_id="test-zmq-server",
        ignore_TD_errors=True,
    )


def test_01(
    object_proxy_thing1_http: "ObjectProxy",
    object_proxy_thing1_mqtt: "ObjectProxy",
    object_proxy_thing1_zmq: "ObjectProxy",
):
    pass
