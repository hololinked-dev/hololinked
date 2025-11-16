import logging
import time

from typing import Any, Generator
from uuid import uuid4

import pytest

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
def thing() -> Generator[TestThing, None, None]:
    thing_id = f"test-thing-{uuid4().hex[:8]}"
    thing = TestThing(id=thing_id)
    thing.run_with_zmq_server(forked=True)
    yield thing
    thing.rpc_server.stop()


@pytest.fixture(scope="module")
def thing_model(thing: TestThing) -> dict[str, Any]:
    return thing.get_thing_model(ignore_errors=True).json()


@pytest.fixture(scope="module")
def client(thing: TestThing):
    client = ClientFactory.zmq(
        thing.id,
        thing.id,
        "IPC",
        ignore_TD_errors=True,
    )
    return client


@pytest.mark.order(1)
def test_creation_and_handshake(client: ObjectProxy, thing_model: dict[str, Any]) -> None:
    assert isinstance(client, ObjectProxy)
    assert len(client.properties) + len(client.actions) + len(client.events) >= (
        len(thing_model["properties"]) + len(thing_model["actions"]) + len(thing_model["events"])
    )


@pytest.mark.order(2)
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(fake.text(max_nb_chars=100), id="text"),
        pytest.param(fake.sentence(), id="sentence"),
        pytest.param(fake.json(), id="json"),
    ],
)
def test_invoke_action_manual(client: ObjectProxy, payload: Any) -> None:
    """call invoke_action with different payloads explicitly"""
    assert client.invoke_action("action_echo", payload) == payload


@pytest.mark.order(3)
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(fake.chrome(), id="chrome"),
        pytest.param(fake.sha256(), id="sha256"),
        pytest.param(fake.address(), id="address"),
    ],
)
def test_invoke_action_dot_notation(client: ObjectProxy, payload: Any) -> None:
    """call invoke_action with different payloads using dot notation"""
    assert client.action_echo(payload) == payload


@pytest.mark.order(4)
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(fake.random_number(), id="random-number"),
        pytest.param(fake.random_int(), id="random-int"),
    ],
)
def test_invoke_action_oneway(client: ObjectProxy, payload: Any) -> None:
    assert client.invoke_action("set_non_remote_number_prop", payload, oneway=True) is None
    assert client.get_non_remote_number_prop() == payload


@pytest.mark.order(5)
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(fake.pylist(20, value_types=[int, float, str, bool]), id="pylist-explicit-types"),
    ],
)
def test_invoke_action_noblock(client: ObjectProxy, payload: Any) -> None:
    noblock_msg_id = client.invoke_action("action_echo", payload, noblock=True)
    assert isinstance(noblock_msg_id, str)
    assert client.invoke_action("action_echo", fake.pylist(20, value_types=[int, float, str, bool])) == fake.last
    assert client.invoke_action("action_echo", fake.pylist(10, value_types=[int, float, str, bool])) == fake.last
    assert client.read_reply(noblock_msg_id) == payload


@pytest.mark.order(6)
def test_read_property_manual(client: ObjectProxy) -> None:
    # Read
    assert isinstance(client.read_property("number_prop"), (int, float))
    assert isinstance(client.read_property("string_prop"), str)
    assert client.read_property("selector_prop") in TestThing.selector_prop.objects


@pytest.mark.order(7)
@pytest.mark.parametrize(
    "prop, payload",
    [
        pytest.param("number_prop", fake.random_number(), id="random-number"),
        pytest.param(
            "selector_prop",
            TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)],
            id="selector-value",
        ),
        pytest.param(
            "observable_list_prop",
            fake.pylist(25, value_types=[int, float, str, bool]),
            id="observable-list",
        ),
    ],
)
def test_write_property_manual(client: ObjectProxy, prop: str, payload: Any) -> None:
    """check if writing properties agrees with read value"""
    client.write_property(prop, payload)
    assert client.read_property(prop) == payload


@pytest.mark.order(8)
def test_read_property_dot_notation(client: ObjectProxy) -> None:
    """read properties using dot notation"""
    assert isinstance(client.number_prop, (int, float))
    assert isinstance(client.string_prop, str)
    assert client.selector_prop in TestThing.selector_prop.objects


@pytest.mark.order(9)
def test_write_property_dot_notation(client: ObjectProxy) -> None:
    """
    write properties using dot notation, unfortunately using parametrization here will not achieve the purpose,
    so its explicitly written out
    """
    client.number_prop = fake.random_number()
    assert client.number_prop == fake.last
    client.selector_prop = TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)]
    assert client.selector_prop == TestThing.selector_prop.objects[fake.last]
    client.observable_list_prop = fake.pylist(25, value_types=[int, float, str, bool])
    assert client.observable_list_prop == fake.last


@pytest.mark.order(10)
@pytest.mark.parametrize(
    "prop, payload",
    [
        pytest.param("number_prop", fake.random_number(), id="random-number"),
        pytest.param(
            "selector_prop",
            TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)],
            id="selector-value",
        ),
        pytest.param(
            "observable_list_prop",
            fake.pylist(25, value_types=[int, float, str, bool]),
            id="observable-list",
        ),
    ],
)
def test_write_property_oneway(client: ObjectProxy, prop: str, payload: Any) -> None:
    """write property one way"""
    client.write_property(prop, payload, oneway=True)
    assert client.read_property(prop) == payload


@pytest.mark.order(11)
def test_read_property_noblock(client: ObjectProxy) -> None:
    """read and write property with noblock"""
    noblock_msg_id = client.read_property("number_prop", noblock=True)
    assert isinstance(noblock_msg_id, str)
    assert client.read_property("selector_prop") in TestThing.selector_prop.objects
    assert isinstance(client.read_property("string_prop"), str)
    assert client.read_reply(noblock_msg_id) == client.number_prop


@pytest.mark.order(12)
def test_write_property_noblock(client: ObjectProxy) -> None:
    """write property with noblock"""
    noblock_msg_id = client.write_property("number_prop", fake.random_number(), noblock=True)
    assert isinstance(noblock_msg_id, str)
    assert client.read_property("number_prop") == fake.last
    assert client.read_reply(noblock_msg_id) is None


@pytest.mark.order(13)
def test_error_handling(client: ObjectProxy) -> None:
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


@pytest.mark.order(14)
def test_rw_multiple_properties(client: ObjectProxy) -> None:
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


@pytest.mark.order(15)
def test_05_subscribe_event(client: ObjectProxy) -> None:
    results = []

    def cb(value: SSE):
        results.append(value)

    client.subscribe_event("test_event", cb)
    time.sleep(1)
    client.push_events()
    time.sleep(3)
    assert len(results) > 0, "No events received"
    assert len(results) == 100, f"Expected 100 events, got {len(results)}"
    client.unsubscribe_event("test_event")


@pytest.mark.order(16)
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
def test_06_observe_properties(
    client: ObjectProxy,
    prop: str,
    prospective_values: Any,
    op: str,
) -> None:
    # Check attribute
    assert hasattr(client, f"{prop}_change_event")
    # req 1 - observable events come due to writing a property
    result = []
    attempt = 0

    def cb(value: SSE):
        nonlocal attempt
        result.append(value)
        attempt += 1

    client.observe_property(prop, cb)
    time.sleep(3)
    for value in prospective_values:
        if op == "read":
            _ = client.read_property(prop)
        else:
            client.write_property(prop, value)

    for _ in range(20):
        if attempt == len(prospective_values):
            break
        time.sleep(0.1)
    client.unobserve_property(prop)
    for index, res in enumerate(result):
        assert res.data == prospective_values[index]


@pytest.mark.order(17)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(fake.text(max_nb_chars=100), id="text"),
        pytest.param(fake.sentence(), id="sentence"),
        pytest.param(fake.json(), id="json"),
    ],
)
async def test_async_invoke_action(client: ObjectProxy, payload: Any) -> None:
    result = await client.async_invoke_action("action_echo", payload)
    assert result == payload


@pytest.mark.order(18)
@pytest.mark.asyncio
async def test_async_read_property(client: ObjectProxy) -> None:
    assert isinstance(await client.async_read_property("number_prop"), (int, float))
    assert isinstance(await client.async_read_property("string_prop"), str)
    assert await client.async_read_property("selector_prop") in TestThing.selector_prop.objects


@pytest.mark.order(19)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prop, payload",
    [
        pytest.param("number_prop", fake.random_number(), id="random-number"),
        pytest.param(
            "selector_prop",
            TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)],
            id="selector-value",
        ),
        pytest.param(
            "observable_list_prop",
            fake.pylist(25, value_types=[int, float, str, bool]),
            id="observable-list",
        ),
    ],
)
async def test_async_write_property(client: ObjectProxy, prop: str, payload: Any) -> None:
    await client.async_write_property(prop, payload)
    assert await client.async_read_property(prop) == payload
