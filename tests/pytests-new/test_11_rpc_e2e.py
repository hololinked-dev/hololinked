# an end to end through the zmq object proxy client with IPC protocol which is assumed to be most stable

# --- Pytest version below ---
import time
import logging
import pytest
from uuid import uuid4
from hololinked.client.abstractions import SSE
from hololinked.client.factory import ClientFactory
from hololinked.client.proxy import ObjectProxy
from hololinked.logger import setup_logging

try:
    from .things import TestThing
    from .utils import fake
except ImportError:
    from things import TestThing
    from utils import fake

setup_logging(log_level=logging.ERROR + 10)


@pytest.fixture(scope="module")
def thing_and_model():
    thing_id = f"test-thing-{uuid4().hex[:8]}"
    thing = TestThing(id=thing_id)
    thing.run_with_zmq_server(forked=True)
    thing_model = thing.get_thing_model(ignore_errors=True).json()
    yield thing, thing_model
    thing.rpc_server.stop()


@pytest.fixture(scope="module")
def client(thing_and_model):
    thing, _ = thing_and_model
    client = ClientFactory.zmq(
        thing.id,
        thing.id,
        "IPC",
        ignore_TD_errors=True,
    )
    return client


def test_01_creation_and_handshake(client, thing_and_model):
    _, thing_model = thing_and_model
    assert isinstance(client, ObjectProxy)
    assert len(client.properties) + len(client.actions) + len(client.events) >= len(thing_model["properties"]) + len(
        thing_model["actions"]
    ) + len(thing_model["events"])


@pytest.mark.parametrize(
    "input_func",
    [
        lambda: fake.text(max_nb_chars=100),
        lambda: fake.sentence(),
        lambda: fake.json(),
    ],
)
def test_02_invoke_action_reply(client, input_func):
    payload = input_func()
    assert client.invoke_action("action_echo", payload) == fake.last


@pytest.mark.parametrize(
    "input_func",
    [
        lambda: fake.chrome(),
        lambda: fake.sha256(),
        lambda: fake.address(),
    ],
)
def test_02_invoke_action_dot(client, input_func):
    payload = input_func()
    assert client.action_echo(payload) == fake.last


def test_02_invoke_action_oneway(client):
    payload = fake.random_number()
    assert client.invoke_action("set_non_remote_number_prop", payload, oneway=True) is None
    assert client.get_non_remote_number_prop() == fake.last


def test_02_invoke_action_noblock(client):
    noblock_payload = fake.pylist(20, value_types=[int, float, str, bool])
    noblock_msg_id = client.invoke_action("action_echo", noblock_payload, noblock=True)
    assert isinstance(noblock_msg_id, str)
    assert client.invoke_action("action_echo", fake.pylist(20, value_types=[int, float, str, bool])) == fake.last
    assert client.invoke_action("action_echo", fake.pylist(10, value_types=[int, float, str, bool])) == fake.last
    assert client.read_reply(noblock_msg_id) == noblock_payload


def test_03_rwd_properties(client):
    # Read
    assert isinstance(client.read_property("number_prop"), (int, float))
    assert isinstance(client.read_property("string_prop"), str)
    assert client.read_property("selector_prop") in TestThing.selector_prop.objects
    # Write
    client.write_property("number_prop", fake.random_number())
    assert client.read_property("number_prop") == fake.last
    sel_val = TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)]
    client.write_property("selector_prop", sel_val)
    assert client.read_property("selector_prop") == TestThing.selector_prop.objects[fake.last]
    client.write_property("observable_list_prop", fake.pylist(25, value_types=[int, float, str, bool]))
    assert client.read_property("observable_list_prop") == fake.last
    # Dot notation
    assert isinstance(client.number_prop, (int, float))
    assert isinstance(client.string_prop, str)
    assert client.selector_prop in TestThing.selector_prop.objects
    client.number_prop = fake.random_number()
    assert client.number_prop == fake.last
    client.selector_prop = TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)]
    assert client.selector_prop == TestThing.selector_prop.objects[fake.last]
    client.observable_list_prop = fake.pylist(25, value_types=[int, float, str, bool])
    assert client.observable_list_prop == fake.last
    # Oneway
    client.write_property("number_prop", fake.random_number(), oneway=True)
    assert client.read_property("number_prop") == fake.last
    client.write_property(
        "selector_prop",
        TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)],
        oneway=True,
    )
    assert client.read_property("selector_prop") == TestThing.selector_prop.objects[fake.last]
    client.write_property(
        "observable_list_prop",
        fake.pylist(25, value_types=[int, float, str, bool]),
        oneway=True,
    )
    assert client.read_property("observable_list_prop") == fake.last
    # Noblock
    noblock_msg_id = client.read_property("number_prop", noblock=True)
    assert isinstance(noblock_msg_id, str)
    assert client.read_property("selector_prop") in TestThing.selector_prop.objects
    assert isinstance(client.read_property("string_prop"), str)
    assert client.read_reply(noblock_msg_id) == client.number_prop
    noblock_msg_id = client.write_property("number_prop", fake.random_number(), noblock=True)
    assert isinstance(noblock_msg_id, str)
    assert client.read_property("number_prop") == fake.last
    assert client.read_reply(noblock_msg_id) is None
    # Exception propagation
    client.string_prop = "world"
    assert client.string_prop == "world"
    with pytest.raises(ValueError):
        client.string_prop = "WORLD"
    with pytest.raises(TypeError):
        client.int_prop = "5"
    # Non-remote prop
    with pytest.raises(AttributeError):
        _ = client.non_remote_number_prop


def test_04_RW_multiple_properties(client):
    client.write_multiple_properties(number_prop=15, string_prop="foobar")
    assert client.number_prop == 15
    assert client.string_prop == "foobar"
    client.int_prop = 5
    client.selector_prop = "b"
    client.number_prop = -15
    props = client.read_multiple_properties(names=["selector_prop", "int_prop", "number_prop", "string_prop"])
    assert props["selector_prop"] == "b"
    assert props["int_prop"] == 5
    assert props["number_prop"] == -15
    assert props["string_prop"] == "foobar"


def test_05_subscribe_event(client):
    results = []

    def cb(value: SSE):
        results.append(value)

    client.subscribe_event("test_event", cb)
    time.sleep(1)
    client.push_events()
    time.sleep(3)
    assert len(results) > 0, "No events received"
    assert len(results) == 100
    client.unsubscribe_event("test_event")


def test_06_observe_properties(client):
    # Check attribute
    assert hasattr(client, "observable_list_prop_change_event")
    assert hasattr(client, "observable_readonly_prop_change_event")
    # req 1 - observable events come due to writing a property
    propective_values = [
        [1, 2, 3, 4, 5],
        ["a", "b", "c", "d", "e"],
        [1, "a", 2, "b", 3],
    ]
    result = []
    attempt = [0]

    def cb(value: SSE):
        assert value.data == propective_values[attempt[0]]
        result.append(value)
        attempt[0] += 1

    client.observe_property("observable_list_prop", cb)
    time.sleep(3)
    for value in propective_values:
        client.observable_list_prop = value
    for _ in range(20):
        if attempt[0] == len(propective_values):
            break
        time.sleep(0.1)
    client.unobserve_property("observable_list_prop")
    for res in result:
        assert res.data in propective_values
    # req 2 - observable events come due to reading a property
    propective_values2 = [1, 2, 3, 4, 5]
    result2 = []
    attempt2 = [0]

    def cb2(value: SSE):
        assert value.data == propective_values2[attempt2[0]]
        result2.append(value)
        attempt2[0] += 1

    client.observe_property("observable_readonly_prop", cb2)
    time.sleep(3)
    for _ in propective_values2:
        _ = client.observable_readonly_prop
    for _ in range(20):
        if attempt2[0] == len(propective_values2):
            break
        time.sleep(0.1)
    client.unobserve_property("observable_readonly_prop")
    for res in result2:
        assert res.data in propective_values2


# --- Async tests ---
import asyncio


@pytest.fixture(scope="module")
def async_thing_and_model():
    thing_id = f"test-thing-{uuid4().hex[:8]}"
    thing = TestThing(id=thing_id)
    thing.run_with_zmq_server(forked=True)
    thing_model = thing.get_thing_model(ignore_errors=True).json()
    yield thing, thing_model
    thing.rpc_server.stop()


@pytest.fixture(scope="module")
def async_client(async_thing_and_model):
    thing, _ = async_thing_and_model
    client = ClientFactory.zmq(
        thing.id,
        thing.id,
        "IPC",
        ignore_TD_errors=True,
    )
    return client


@pytest.mark.asyncio
async def test_async_01_creation_and_handshake(async_client, async_thing_and_model):
    _, thing_model = async_thing_and_model
    assert isinstance(async_client, ObjectProxy)
    assert len(async_client.properties) + len(async_client.actions) + len(async_client.events) >= len(
        thing_model["properties"]
    ) + len(thing_model["actions"]) + len(thing_model["events"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_func",
    [
        lambda: fake.text(max_nb_chars=100),
        lambda: fake.sentence(),
        lambda: fake.json(),
    ],
)
async def test_async_02_invoke_action(async_client, input_func):
    payload = input_func()
    result = await async_client.async_invoke_action("action_echo", payload)
    assert result == fake.last


@pytest.mark.asyncio
async def test_async_03_rwd_properties(async_client):
    assert isinstance(await async_client.async_read_property("number_prop"), (int, float))
    assert isinstance(await async_client.async_read_property("string_prop"), str)
    assert await async_client.async_read_property("selector_prop") in TestThing.selector_prop.objects
    await async_client.async_write_property("number_prop", fake.random_number())
    assert await async_client.async_read_property("number_prop") == fake.last
    sel_val = TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)]
    await async_client.async_write_property("selector_prop", sel_val)
    assert await async_client.async_read_property("selector_prop") == TestThing.selector_prop.objects[fake.last]
    await async_client.async_write_property(
        "observable_list_prop", fake.pylist(25, value_types=[int, float, str, bool])
    )
    assert await async_client.async_read_property("observable_list_prop") == fake.last
