import itertools
import time

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
    from tests.things import TestThing
except ImportError:
    from test_14_protocols_http import wait_until_server_ready
    from test_16_protocols_mqtt import (  # noqa: F401
        mosquitto_container,
        mqtt_host,
        mqtt_port,
        mqtt_ssl_context,
    )
    from things import TestThing

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
def thing2() -> TestThing:
    return TestThing(id=f"test-thing-{uuid_hex()}", serial_number="simulation")


@pytest.fixture(scope="module")
@pytest.mark.asyncio
def things(
    mosquitto_container: MosquittoContainer,  # place holder to boot it up
    thing1: TestThing,
    thing2: TestThing,
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

    run(http_server, mqtt_publisher, zmq_server, forked=True, print_welcome_message=False)
    wait_until_server_ready(port=http_port)
    yield thing1, thing2
    stop()


hostname_prefix = "http://127.0.0.1"


@pytest.fixture(scope="module")
def td1_endpoint(things: tuple[TestThing, TestThing], http_port: int) -> str:
    thing1, _ = things
    return f"{hostname_prefix}:{http_port}/{thing1.id}/resources/wot-td"


@pytest.fixture(scope="module")
def td2_endpoint(things: tuple[TestThing, TestThing], http_port: int) -> str:
    _, thing2 = things
    return f"{hostname_prefix}:{http_port}/{thing2.id}/resources/wot-td"


@pytest.fixture(scope="module")
def object_proxy_thing1_http(td1_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td1_endpoint, ignore_TD_errors=True)


@pytest.fixture(scope="module")
def object_proxy_thing2_http(td2_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td2_endpoint, ignore_TD_errors=True)


@pytest.fixture(scope="module")
async def object_proxy_thing1_mqtt(
    mqtt_host: str,
    mqtt_port: int,
    things: tuple[TestThing, TestThing],
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
async def object_proxy_thing2_mqtt(
    mqtt_host: str,
    mqtt_port: int,
    things: tuple[TestThing, TestThing],
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
def object_proxy_thing1_zmq(things: tuple[TestThing, TestThing]) -> "ObjectProxy":
    thing1, _ = things
    return ClientFactory.zmq(
        access_point="IPC",
        thing_id=thing1.id,
        server_id="test-zmq-server",
        ignore_TD_errors=True,
    )


@pytest.fixture(scope="module")
def object_proxy_thing2_zmq(things: tuple[TestThing, TestThing]) -> "ObjectProxy":
    _, thing2 = things
    return ClientFactory.zmq(
        access_point="IPC",
        thing_id=thing2.id,
        server_id="test-zmq-server",
        ignore_TD_errors=True,
    )


async def test_01_rw_properties(
    object_proxy_thing1_http: "ObjectProxy",
    object_proxy_thing1_zmq: "ObjectProxy",
    object_proxy_thing2_http: "ObjectProxy",
    object_proxy_thing2_zmq: "ObjectProxy",
):
    assert object_proxy_thing1_http.read_property("string_prop") == object_proxy_thing1_zmq.read_property("string_prop")
    assert object_proxy_thing2_http.read_property("string_prop") == object_proxy_thing2_zmq.read_property("string_prop")

    object_proxy_thing1_http.write_property("string_prop", "newvalueone")
    object_proxy_thing2_http.write_property("string_prop", "newvaluetwo")
    assert object_proxy_thing1_zmq.read_property("string_prop") == "newvalueone"
    assert object_proxy_thing2_zmq.read_property("string_prop") == "newvaluetwo"
    assert object_proxy_thing1_http.read_property("string_prop") == object_proxy_thing1_zmq.read_property("string_prop")
    assert object_proxy_thing2_http.read_property("string_prop") == object_proxy_thing2_zmq.read_property("string_prop")


async def test_02_observe_properties(
    object_proxy_thing1_http: "ObjectProxy",
    object_proxy_thing1_mqtt: "ObjectProxy",
    object_proxy_thing1_zmq: "ObjectProxy",
):
    observed_values_http = []
    observed_values_mqtt = []
    observed_values_zmq = []

    def callback_http(value):
        observed_values_http.append(value)

    def callback_zmq(value):
        observed_values_zmq.append(value)

    def callback_mqtt(value):
        observed_values_mqtt.append(value)

    object_proxy_thing1_http.observe_property("observable_readonly_prop", callbacks=callback_http)
    object_proxy_thing1_zmq.observe_property("observable_readonly_prop", callbacks=callback_zmq)
    object_proxy_thing1_mqtt.observe_property("observable_readonly_prop", callbacks=callback_mqtt)

    total_events = 100
    for i in range(total_events):
        object_proxy_thing1_zmq.read_property("observable_readonly_prop")
        time.sleep(0.02)  # cannot say how good the CI CD machiens are,
        # so let's give it some time to process events and not miss any of them

    time.sleep(3)  # wait for all events to be processed

    assert len(observed_values_zmq) > 0, "No values observed through ZMQ client"
    assert len(observed_values_mqtt) > 0, "No values observed through MQTT client"

    if len(observed_values_http) > 0:
        assert abs(len(observed_values_http) - total_events) < 3, (
            f"Expected around {total_events} events, got {len(observed_values_http)} through HTTP client"
        )
    assert abs(len(observed_values_zmq) - total_events) < 3, (
        f"Expected around {total_events} events, got {len(observed_values_zmq)} through ZMQ client"
    )
    assert abs(len(observed_values_mqtt) - total_events) < 3, (
        f"Expected around {total_events} events, got {len(observed_values_mqtt)} through MQTT client"
    )

    object_proxy_thing1_http.unobserve_property("observable_readonly_prop")
    object_proxy_thing1_zmq.unobserve_property("observable_readonly_prop")
    object_proxy_thing1_mqtt.unobserve_property("observable_readonly_prop")


async def test_03_invoke_action(
    object_proxy_thing1_http: "ObjectProxy",
    object_proxy_thing1_zmq: "ObjectProxy",
    object_proxy_thing2_http: "ObjectProxy",
    object_proxy_thing2_zmq: "ObjectProxy",
):
    object_proxy_thing1_http.invoke_action("set_non_remote_number_prop", 10)
    assert object_proxy_thing1_zmq.invoke_action("get_non_remote_number_prop") == 10

    object_proxy_thing2_http.invoke_action("set_non_remote_number_prop", 20)
    assert object_proxy_thing2_zmq.invoke_action("get_non_remote_number_prop") == 20


async def test_04_subscribe_event(
    object_proxy_thing2_http: "ObjectProxy",
    object_proxy_thing2_mqtt: "ObjectProxy",
    object_proxy_thing2_zmq: "ObjectProxy",
):
    observed_values_http = []
    observed_values_mqtt = []
    observed_values_zmq = []

    def callback_http(value):
        observed_values_http.append(value)

    def callback_zmq(value):
        observed_values_zmq.append(value)

    def callback_mqtt(value):
        observed_values_mqtt.append(value)

    object_proxy_thing2_mqtt.subscribe_event("test_event", callback_mqtt)
    object_proxy_thing2_zmq.subscribe_event("test_event", callback_zmq)
    object_proxy_thing2_http.subscribe_event("test_event", callback_http)

    time.sleep(3)

    total_events = 10

    for i in range(total_events):
        object_proxy_thing2_http.push_events(total_number_of_events=1)
        time.sleep(0.02)  # cannot say how good the CI CD machiens are,
        # so let's give it some time to process events and not miss any of them

    time.sleep(3)

    assert len(observed_values_http) > 0, "No events received through HTTP client"
    assert len(observed_values_mqtt) > 0, "No events received through MQTT client"
    assert len(observed_values_zmq) > 0, "No events received through ZMQ client"

    if len(observed_values_http) > 0:
        assert abs(len(observed_values_http) - total_events) < 3, (
            f"Expected {total_events} events, got {len(observed_values_http)} through HTTP client"
        )
    assert abs(len(observed_values_mqtt) - total_events) < 3, (
        f"Expected {total_events} events, got {len(observed_values_mqtt)} through MQTT client"
    )
    assert abs(len(observed_values_zmq) - total_events) < 3, (
        f"Expected {total_events} events, got {len(observed_values_zmq)} through ZMQ client"
    )

    object_proxy_thing2_mqtt.unsubscribe_event("test_event")
    object_proxy_thing2_zmq.unsubscribe_event("test_event")
    object_proxy_thing2_http.unsubscribe_event("test_event")
