import time

from typing import Any, Generator

import pytest

from hololinked.client.abstractions import SSE
from hololinked.client.factory import ClientFactory
from hololinked.client.proxy import ObjectProxy
from hololinked.utils import uuid_hex


try:
    from .things import TestThing
    from .utils import fake
except ImportError:
    from things import TestThing
    from utils import fake


@pytest.fixture(scope="class")
def access_point(request) -> str:
    return "INPROC"


@pytest.fixture(scope="class")
def thing(access_point) -> Generator[TestThing, None, None]:
    thing_id = f"test-thing-{uuid_hex()}"
    thing = TestThing(id=thing_id)
    thing.run_with_zmq_server(forked=True, access_points=[access_point])
    yield thing
    thing.rpc_server.stop()


@pytest.fixture(scope="class")
def thing_model(thing: TestThing) -> dict[str, Any]:
    return thing.get_thing_model(ignore_errors=True).json()


@pytest.fixture(scope="class")
def client(thing: TestThing, access_point: str) -> Generator[ObjectProxy, None, None]:
    client = ClientFactory.zmq(
        server_id=thing.id,
        thing_id=thing.id,
        access_point=access_point.replace("*", "localhost"),
        ignore_TD_errors=True,
    )
    yield client
    # client.close()


@pytest.mark.asyncio(loop_scope="class")
class TestRPC_E2E:
    """End-to-end tests for RPC"""

    def test_01_creation_and_handshake(self, client: ObjectProxy, thing_model: dict[str, Any]):
        assert isinstance(client, ObjectProxy)
        assert len(client.properties) + len(client.actions) + len(client.events) >= (
            len(thing_model["properties"]) + len(thing_model["actions"]) + len(thing_model["events"])
        )

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(fake.text(max_nb_chars=100), id="text"),
            pytest.param(fake.sentence(), id="sentence"),
            pytest.param(fake.json(), id="json"),
        ],
    )
    def test_02_invoke_action_manual(self, client: ObjectProxy, payload: Any):
        assert client.invoke_action("action_echo", payload) == payload

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(fake.chrome(), id="chrome"),
            pytest.param(fake.sha256(), id="sha256"),
            pytest.param(fake.address(), id="address"),
        ],
    )
    def test_03_invoke_action_dot_notation(self, client: ObjectProxy, payload: Any):
        assert client.action_echo(payload) == payload

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(fake.random_number(), id="random-number"),
            pytest.param(fake.random_int(), id="random-int"),
        ],
    )
    def test_04_invoke_action_oneway(self, client: ObjectProxy, payload: Any):
        assert client.invoke_action("set_non_remote_number_prop", payload, oneway=True) is None
        assert client.get_non_remote_number_prop() == payload

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(
                fake.pylist(20, value_types=[int, float, str, bool]),
                id="pylist-explicit-types",
            ),
        ],
    )
    def test_05_invoke_action_noblock(self, client: ObjectProxy, payload: Any):
        noblock_msg_id = client.invoke_action("action_echo", payload, noblock=True)
        assert isinstance(noblock_msg_id, str)
        assert client.invoke_action("action_echo", fake.pylist(20, value_types=[int, float, str, bool])) == fake.last
        assert client.invoke_action("action_echo", fake.pylist(10, value_types=[int, float, str, bool])) == fake.last
        assert client.read_reply(noblock_msg_id) == payload

    def test_06_read_property_manual(self, client: ObjectProxy):
        assert isinstance(client.read_property("number_prop"), (int, float))
        assert isinstance(client.read_property("string_prop"), str)
        assert client.read_property("selector_prop") in TestThing.selector_prop.objects

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
    def test_07_write_property_manual(self, client: ObjectProxy, prop: str, payload: Any):
        client.write_property(prop, payload)
        assert client.read_property(prop) == payload

    def test_08_read_property_dot_notation(self, client: ObjectProxy):
        assert isinstance(client.number_prop, (int, float))
        assert isinstance(client.string_prop, str)
        assert client.selector_prop in TestThing.selector_prop.objects

    def test_09_write_property_dot_notation(self, client: ObjectProxy):
        client.number_prop = fake.random_number()
        assert client.number_prop == fake.last
        client.selector_prop = TestThing.selector_prop.objects[
            fake.random_int(0, len(TestThing.selector_prop.objects) - 1)
        ]
        assert client.selector_prop == TestThing.selector_prop.objects[fake.last]
        client.observable_list_prop = fake.pylist(25, value_types=[int, float, str, bool])
        assert client.observable_list_prop == fake.last

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
    def test_10_write_property_oneway(self, client: ObjectProxy, prop: str, payload: Any):
        client.write_property(prop, payload, oneway=True)
        assert client.read_property(prop) == payload

    def test_11_read_property_noblock(self, client: ObjectProxy):
        noblock_msg_id = client.read_property("number_prop", noblock=True)
        assert isinstance(noblock_msg_id, str)
        assert client.read_property("selector_prop") in TestThing.selector_prop.objects
        assert isinstance(client.read_property("string_prop"), str)
        assert client.read_reply(noblock_msg_id) == client.number_prop

    def test_12_write_property_noblock(self, client: ObjectProxy):
        noblock_msg_id = client.write_property("number_prop", fake.random_number(), noblock=True)
        assert isinstance(noblock_msg_id, str)
        assert client.read_property("number_prop") == fake.last
        assert client.read_reply(noblock_msg_id) is None

    def test_13_error_handling(self, client: ObjectProxy):
        client.string_prop = "world"
        assert client.string_prop == "world"
        with pytest.raises(ValueError):
            client.string_prop = "WORLD"
        with pytest.raises(TypeError):
            client.int_prop = "5"
        with pytest.raises(AttributeError):
            _ = client.non_remote_number_prop

    def test_14_rw_multiple_properties(self, client: ObjectProxy):
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

    def test_15_subscribe_event(self, client: ObjectProxy):
        results = []

        def cb(value: SSE):
            results.append(value)

        client.subscribe_event("test_event", cb)
        time.sleep(3)

        for i in range(10):
            client.push_events(total_number_of_events=1)
            time.sleep(1)
            if len(results) > 0:
                results.clear()
                break
        else:
            pytest.skip("No events received from server, probably due to OS level issues")

        client.push_events()
        time.sleep(3)
        assert len(results) > 0, "No events received"
        assert abs(len(results) - 100) < 3, f"Expected 100 events, got {len(results)}"
        client.unsubscribe_event("test_event")

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
    def test_16_observe_properties(self, client: ObjectProxy, prop: str, prospective_values: Any, op: str):
        assert hasattr(client, f"{prop}_change_event")
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

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(fake.text(max_nb_chars=100), id="text"),
            pytest.param(fake.sentence(), id="sentence"),
            pytest.param(fake.json(), id="json"),
        ],
    )
    async def test_17_async_invoke_action(self, client, payload):
        result = await client.async_invoke_action("action_echo", payload)
        assert result == payload

    async def test_18_async_read_property(self, client):
        assert isinstance(await client.async_read_property("number_prop"), (int, float))
        assert isinstance(await client.async_read_property("string_prop"), str)
        assert await client.async_read_property("selector_prop") in TestThing.selector_prop.objects

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
    async def test_19_async_write_property(self, client, prop, payload):
        await client.async_write_property(prop, payload)
        assert await client.async_read_property(prop) == payload


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
