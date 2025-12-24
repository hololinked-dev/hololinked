import asyncio
import random
import threading
import time

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Generator

import jsonschema
import pytest
import structlog

from hololinked.client.abstractions import SSE
from hololinked.client.zmq.consumed_interactions import ZMQAction, ZMQEvent, ZMQProperty
from hololinked.core import Thing
from hololinked.core.actions import BoundAction
from hololinked.core.zmq.brokers import (  # noqa: F401
    AsyncZMQClient,
    EventDispatcher,
    SyncZMQClient,
)
from hololinked.core.zmq.rpc_server import RPCServer
from hololinked.td import ActionAffordance, EventAffordance, PropertyAffordance
from hololinked.td.forms import Form
from hololinked.utils import get_all_sub_things_recusively, uuid_hex


try:
    from .test_06_actions import replace_methods_with_actions
    from .things import TestThing
    from .things import test_thing_TD as test_thing_original_TD
except ImportError:
    from test_06_actions import replace_methods_with_actions
    from things import TestThing
    from things import test_thing_TD as test_thing_original_TD


@pytest.fixture(scope="module")
def data_structures():
    return [
        {"key": "value"},
        [1, 2, 3],
        "string",
        42,
        3.14,
        True,
        None,
        {"nested": {"key": "value"}},
        [{"list": "of"}, {"dicts": "here"}],
        {"complex": {"nested": {"list": [1, 2, 3]}, "mixed": [1, "two", 3.0, None]}},
        {"array": [1, 2, 3]},
    ]


@pytest.fixture(scope="class")
def thing_id():
    return f"test-thing-{uuid_hex()}"


@pytest.fixture(scope="class")
def server_id():
    return f"test-server-{uuid_hex()}"


@pytest.fixture(scope="class")
def client_id():
    return f"test-client-{uuid_hex()}"


@pytest.fixture(scope="class")
def owner_inst():
    return SimpleNamespace(_noblock_messages={})


@pytest.fixture(scope="class")
def test_thing_TD(thing_id) -> dict[str, Any]:
    td = deepcopy(test_thing_original_TD)
    td["id"] = thing_id
    return td


@pytest.fixture(scope="class")
def thing(thing_id: str) -> TestThing:
    cls = deepcopy(TestThing)
    replace_methods_with_actions(cls)
    return cls(id=thing_id)


@pytest.fixture(scope="class")
def server(server_id, thing) -> Generator[RPCServer, None, None]:
    _server = RPCServer(id=server_id, things=[thing])
    thread = threading.Thread(target=_server.run, daemon=False)
    thread.start()
    yield _server
    _server.stop()


@pytest.fixture(scope="class")
def async_client(client_id, server_id) -> Generator[AsyncZMQClient, None, None]:
    client = AsyncZMQClient(
        id=client_id,
        server_id=server_id,
        access_point="INPROC",
        handshake=False,
    )
    yield client
    client.exit()


@pytest.fixture(scope="class")
def sync_client(client_id, server_id) -> Generator[SyncZMQClient, None, None]:
    client = SyncZMQClient(
        id=client_id + "-sync",
        server_id=server_id,
        access_point="INPROC",
        handshake=False,
    )
    yield client
    client.exit()


@pytest.fixture(scope="class")
def action_echo(test_thing_TD, sync_client, async_client, owner_inst):
    return ZMQAction(
        resource=ActionAffordance.from_TD("action_echo", test_thing_TD),
        sync_client=sync_client,
        async_client=async_client,
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
        invokation_timeout=5,
        execution_timeout=5,
    )


@pytest.fixture(scope="class")
def action_get_serialized_data(test_thing_TD, sync_client, async_client, owner_inst):
    return ZMQAction(
        resource=ActionAffordance.from_TD("get_serialized_data", test_thing_TD),
        sync_client=sync_client,
        async_client=async_client,
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
        invokation_timeout=5,
        execution_timeout=5,
    )


@pytest.fixture(scope="class")
def action_sleep(test_thing_TD, sync_client, async_client, owner_inst):
    return ZMQAction(
        resource=ActionAffordance.from_TD("sleep", test_thing_TD),
        sync_client=sync_client,
        async_client=async_client,
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
        invokation_timeout=5,
        execution_timeout=5,
    )


@pytest.fixture(scope="class")
def action_get_mixed_content_data(test_thing_TD, sync_client, async_client, owner_inst):
    return ZMQAction(
        resource=ActionAffordance.from_TD("get_mixed_content_data", test_thing_TD),
        sync_client=sync_client,
        async_client=async_client,
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
        invokation_timeout=5,
        execution_timeout=5,
    )


@pytest.fixture(scope="class")
def action_push_events(test_thing_TD, sync_client, async_client, owner_inst):
    return ZMQAction(
        resource=ActionAffordance.from_TD("push_events", test_thing_TD),
        sync_client=sync_client,
        async_client=async_client,
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
        invokation_timeout=5,
        execution_timeout=5,
    )


@pytest.fixture(scope="class")
def base_property(test_thing_TD, sync_client, async_client, owner_inst):
    return ZMQProperty(
        resource=PropertyAffordance.from_TD("base_property", test_thing_TD),
        sync_client=sync_client,
        async_client=async_client,
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
        invokation_timeout=5,
        execution_timeout=5,
    )


@pytest.fixture(scope="class")
def total_number_of_events(test_thing_TD, sync_client, async_client, owner_inst):
    return ZMQProperty(
        resource=PropertyAffordance.from_TD("total_number_of_events", test_thing_TD),
        sync_client=sync_client,
        async_client=async_client,
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
        invokation_timeout=5,
        execution_timeout=5,
    )


@pytest.fixture(scope="class")
def test_event(test_thing_TD, owner_inst):
    return ZMQEvent(
        resource=EventAffordance.from_TD("test_event", test_thing_TD),
        owner_inst=owner_inst,
        logger=structlog.get_logger(),
    )


@pytest.mark.asyncio(loop_scope="class")
class TestRPCBroker:
    def test_01_creation_defaults(self, server: RPCServer, thing: TestThing):
        assert server.req_rep_server.socket_address.startswith("inproc://")
        assert server.event_publisher.socket_address.startswith("inproc://")
        assert thing.rpc_server == server
        assert thing.event_publisher == server.event_publisher

    def test_02_handshake(self, sync_client: SyncZMQClient):
        sync_client.handshake()

    async def test_02_async_handshake(self, async_client: AsyncZMQClient):
        async_client.handshake()
        await async_client.handshake_complete()

    async def test_03_action_abstraction_basic(self, action_echo: ZMQAction):
        await action_echo.async_call("value")
        action_echo.oneway(5)
        noblock_msg_id = action_echo.noblock(10)
        assert action_echo.last_return_value == "value"
        response = action_echo._sync_zmq_client.recv_response(noblock_msg_id)
        action_echo._last_zmq_response = response
        assert action_echo.last_return_value == 10
        assert action_echo(2) == 2

    async def test_04_action_abstraction_thorough(self, action_echo: ZMQAction, data_structures: list[Any]):
        msg_ids = [None for _ in range(len(data_structures))]
        last_call_type = None
        for index, data in enumerate(data_structures):
            call_type = random.choice(["async_call", "plain_call", "oneway", "noblock"])
            if call_type == "async_call":
                result = await action_echo.async_call(data)
                assert result == data
            elif call_type == "plain_call":
                result = action_echo(data)
                assert result == data
            elif call_type == "oneway":
                action_echo.oneway(data)
                assert data != action_echo.last_return_value
            elif call_type == "noblock":
                msg_ids[index] = action_echo.noblock(data)
                assert data != action_echo.last_return_value
            if last_call_type == "noblock":
                response = action_echo._sync_zmq_client.recv_response(msg_ids[index - 1])
                action_echo._last_zmq_response = response
                assert action_echo.last_return_value == data_structures[index - 1]
            last_call_type = call_type

    async def test_05_property_abstractions_basic(self, base_property: ZMQProperty):
        base_property.set(100)
        assert base_property.get() == 100
        base_property.oneway_set(200)
        assert base_property.get() == 200

        await base_property.async_set(300)
        assert base_property.get() == 300
        await base_property.async_set(0)
        assert await base_property.async_get() == 0

    async def test_06_property_abstractions_thorough(self, base_property: ZMQProperty, data_structures: list[Any]):
        msg_ids = [None for _ in range(len(data_structures))]
        last_call_type = None
        for index, data in enumerate(data_structures):
            call_type = random.choice(["async_set", "set", "oneway_set", "noblock_get"])
            if call_type == "async_set":
                assert await base_property.async_set(data) is None
                assert await base_property.async_get() == data
            elif call_type == "set":
                assert base_property.set(data) is None
                assert base_property.get() == data
            elif call_type == "oneway_set":
                assert base_property.oneway_set(data) is None
                assert data != base_property.last_read_value
                assert data == base_property.get()
            elif call_type == "noblock_get":
                msg_ids[index] = base_property.noblock_get()
                assert data != base_property.last_read_value
            if last_call_type == "noblock":
                response = base_property._sync_zmq_client.recv_response(msg_ids[index - 1])
                base_property._last_zmq_response = response
                assert base_property.last_read_value == data_structures[index - 1]
            last_call_type = call_type

    async def notest_07_thing_execution_context(self, action_echo: ZMQAction):
        old_thing_execution_context = action_echo._thing_execution_context
        action_echo._thing_execution_context = dict(fetch_execution_logs=True)
        await action_echo.async_call("value")
        assert isinstance(action_echo.last_return_value, dict)
        assert "execution_logs" in action_echo.last_return_value.keys()
        assert "return_value" in action_echo.last_return_value.keys()
        assert len(action_echo.last_return_value) == 2
        assert action_echo.last_return_value != "value"
        assert isinstance(action_echo.last_return_value["execution_logs"], list)
        assert action_echo.last_return_value["return_value"] == "value"
        action_echo._thing_execution_context = old_thing_execution_context

    async def test_08_execution_timeout(self, action_sleep: ZMQAction):
        try:
            await action_sleep.async_call()
        except Exception as ex:
            assert isinstance(ex, TimeoutError)
            assert "Execution timeout occured" in str(ex)
        else:
            assert False

    async def test_09_invokation_timeout(self, action_sleep: ZMQAction):
        try:
            old_timeout = action_sleep._invokation_timeout
            action_sleep._invokation_timeout = 0.1
            await action_sleep.async_call()
        except Exception as ex:
            assert isinstance(ex, TimeoutError)
            assert "Invokation timeout occured" in str(ex)
        else:
            assert False
        finally:
            action_sleep._invokation_timeout = old_timeout

    async def test_10_binary_payloads(
        self,
        action_get_mixed_content_data: ZMQAction,
        action_get_serialized_data: ZMQAction,
    ):
        assert action_get_mixed_content_data() == ("foobar", b"foobar")
        assert action_get_serialized_data() == b"foobar"

        await action_get_mixed_content_data.async_call()
        result = action_get_mixed_content_data.last_return_value
        assert result == ("foobar", b"foobar")

        await action_get_serialized_data.async_call()
        result = action_get_serialized_data.last_return_value
        assert result == b"foobar"

    def test_11_exposed_actions(self, thing: TestThing, sync_client: SyncZMQClient):
        client = sync_client

        assert isinstance(thing.action_echo, BoundAction)
        action_echo = ZMQAction(
            resource=thing.action_echo.to_affordance(),
            sync_client=client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        assert action_echo(1) == 1

        assert isinstance(thing.action_echo_with_classmethod, BoundAction)
        action_echo_with_classmethod = ZMQAction(
            resource=thing.action_echo_with_classmethod.to_affordance(),
            sync_client=client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        assert action_echo_with_classmethod(2) == 2

        assert isinstance(thing.action_echo_async, BoundAction)
        action_echo_async = ZMQAction(
            resource=thing.action_echo_async.to_affordance(),
            sync_client=client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        assert action_echo_async("string") == "string"

        assert isinstance(thing.action_echo_async_with_classmethod, BoundAction)
        action_echo_async_with_classmethod = ZMQAction(
            resource=thing.action_echo_async_with_classmethod.to_affordance(),
            sync_client=client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        assert action_echo_async_with_classmethod([1, 2]) == [1, 2]

        assert isinstance(thing.parameterized_action, BoundAction)
        parameterized_action = ZMQAction(
            resource=thing.parameterized_action.to_affordance(),
            sync_client=client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        assert parameterized_action(arg1=1, arg2="hello", arg3=5) == [thing.id, 1, "hello", 5]

        assert isinstance(thing.parameterized_action_async, BoundAction)
        parameterized_action_async = ZMQAction(
            resource=thing.parameterized_action_async.to_affordance(),
            sync_client=client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        assert parameterized_action_async(arg1=2.5, arg2="hello", arg3="foo") == [thing.id, 2.5, "hello", "foo"]

        assert isinstance(thing.parameterized_action_without_call, BoundAction)
        parameterized_action_without_call = ZMQAction(
            resource=thing.parameterized_action_without_call.to_affordance(),
            sync_client=client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )

        with pytest.raises(NotImplementedError) as ex:
            parameterized_action_without_call(arg1=2, arg2="hello", arg3=5)
        assert str(ex.value).startswith("Subclasses must implement __call__")

    def test_12_json_schema_validation(self, thing: TestThing, sync_client: SyncZMQClient):
        assert isinstance(thing.json_schema_validated_action, BoundAction)
        action_affordance = thing.json_schema_validated_action.to_affordance()
        json_schema_validated_action = ZMQAction(
            resource=action_affordance,
            sync_client=sync_client,
            async_client=None,
            owner_inst=None,
            logger=structlog.get_logger(),
        )

        with pytest.raises(Exception) as ex1:
            json_schema_validated_action(val1="1", val2="hello", val3={"field": "value"}, val4=[])
        assert str(ex1.value).startswith("'1' is not of type 'integer'")
        with pytest.raises(Exception) as ex2:
            json_schema_validated_action("1", val2="hello", val3={"field": "value"}, val4=[])
        assert str(ex2.value).startswith("'1' is not of type 'integer'")
        with pytest.raises(Exception) as ex3:
            json_schema_validated_action(1, 2, val3={"field": "value"}, val4=[])
        assert str(ex3.value).startswith("2 is not of type 'string'")
        with pytest.raises(Exception) as ex4:
            json_schema_validated_action(1, "hello", val3="field", val4=[])
        assert str(ex4.value).startswith("'field' is not of type 'object'")
        with pytest.raises(Exception) as ex5:
            json_schema_validated_action(1, "hello", val3={"field": "value"}, val4="[]")
        assert str(ex5.value).startswith("'[]' is not of type 'array'")
        # data with valid schema
        return_value = json_schema_validated_action(val1=1, val2="hello", val3={"field": "value"}, val4=[])
        assert return_value == {"val1": 1, "val3": {"field": "value"}}
        jsonschema.Draft7Validator(action_affordance.output).validate(return_value)

    def test_13_pydantic_validation(self, thing: TestThing, sync_client: SyncZMQClient):
        assert isinstance(thing.pydantic_validated_action, BoundAction)
        action_affordance = thing.pydantic_validated_action.to_affordance()
        pydantic_validated_action = ZMQAction(
            resource=action_affordance,
            sync_client=sync_client,
            async_client=None,
            owner_inst=None,
            logger=structlog.get_logger(),
        )

        with pytest.raises(Exception) as ex1:
            pydantic_validated_action(val1="1", val2="hello", val3={"field": "value"}, val4=[])
        assert (
            "validation error for pydantic_validated_action_input" in str(ex1.value)
            and "val1" in str(ex1.value)
            and "val2" not in str(ex1.value)
            and "val3" not in str(ex1.value)
            and "val4" not in str(ex1.value)
        )
        with pytest.raises(Exception) as ex2:
            pydantic_validated_action("1", val2="hello", val3={"field": "value"}, val4=[])
        assert (
            "validation error for pydantic_validated_action_input" in str(ex2.value)
            and "val1" in str(ex2.value)
            and "val2" not in str(ex2.value)
            and "val3" not in str(ex2.value)
            and "val4" not in str(ex2.value)
        )
        with pytest.raises(Exception) as ex3:
            pydantic_validated_action(1, 2, val3={"field": "value"}, val4=[])
        assert (
            "validation error for pydantic_validated_action_input" in str(ex3.value)
            and "val1" not in str(ex3.value)
            and "val2" in str(ex3.value)
            and "val3" not in str(ex3.value)
            and "val4" not in str(ex3.value)
        )
        with pytest.raises(Exception) as ex4:
            pydantic_validated_action(1, "hello", val3="field", val4=[])
        assert (
            "validation error for pydantic_validated_action_input" in str(ex4.value)
            and "val1" not in str(ex4.value)
            and "val2" not in str(ex4.value)
            and "val3" in str(ex4.value)
            and "val4" not in str(ex4.value)
        )
        with pytest.raises(Exception) as ex5:
            pydantic_validated_action(1, "hello", val3={"field": "value"}, val4="[]")
        assert (
            "validation error for pydantic_validated_action_input" in str(ex5.value)
            and "val1" not in str(ex5.value)
            and "val2" not in str(ex5.value)
            and "val3" not in str(ex5.value)
            and "val4" in str(ex5.value)
        )
        # data with valid schema
        return_value = pydantic_validated_action(val1=1, val2="hello", val3={"field": "value"}, val4=[])
        assert return_value == {"val2": "hello", "val4": []}

    def test_14_property_abstractions(self, thing: TestThing, sync_client: SyncZMQClient):
        descriptor = thing.properties["number_prop"]
        # Property type check is omitted since Property is not imported
        number_prop = ZMQProperty(
            resource=descriptor.to_affordance(thing),
            sync_client=sync_client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        assert number_prop.get() == descriptor.default
        number_prop.set(100)
        assert number_prop.get() == 100
        number_prop.oneway_set(200)
        assert number_prop.get() == 200

    def test_15_json_schema_property(self, thing: TestThing, sync_client: SyncZMQClient):
        """Test json schema based property"""
        json_schema_prop = ZMQProperty(
            resource=TestThing.json_schema_prop.to_affordance(thing),
            sync_client=sync_client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        json_schema_prop.set("hello")
        assert json_schema_prop.get() == "hello"
        json_schema_prop.set("world")
        assert json_schema_prop.get() == "world"

        with pytest.raises(Exception) as ex:
            json_schema_prop.set("world1")
        assert "Failed validating 'pattern' in schema:" in str(ex.value)

    def test_16_pydantic_model_property(self, thing: TestThing, sync_client: SyncZMQClient):
        """Test pydantic model based property"""
        pydantic_prop = ZMQProperty(
            resource=TestThing.pydantic_prop.to_affordance(thing),
            sync_client=sync_client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )

        valid_value = {"foo": "foo", "bar": 1, "foo_bar": 1.0}
        pydantic_prop.set(valid_value)
        assert pydantic_prop.get() == valid_value

        invalid_value = {"foo": 1, "bar": "1", "foo_bar": 1.0}
        with pytest.raises(Exception) as ex:
            pydantic_prop.set(invalid_value)
        assert "validation error for PydanticProp" in str(ex.value)

        pydantic_simple_prop = ZMQProperty(
            resource=TestThing.pydantic_simple_prop.to_affordance(thing),
            sync_client=sync_client,
            async_client=None,
            logger=structlog.get_logger(),
            owner_inst=None,
        )
        pydantic_simple_prop.set(5)
        assert pydantic_simple_prop.get() == 5
        with pytest.raises(Exception) as ex:
            pydantic_simple_prop.set("5str")
        assert "validation error for 'int'" in str(ex.value)

    def test_17_creation_defaults(self, thing: TestThing, server: RPCServer):
        """test server configuration defaults"""
        all_things = get_all_sub_things_recusively(thing)
        # assert len(all_things) > 1  # run the test only if there are sub things
        for thing in all_things:
            assert isinstance(thing, Thing)
            for name, event in thing.events.values.items():
                assert event.publisher == server.event_publisher
                assert isinstance(event._unique_identifier, str)
                assert event._owner_inst == thing

    @pytest.mark.parametrize(
        "event_name, expected_data",
        [
            pytest.param("test_event", "test data", id="test_event"),
            pytest.param("test_binary_payload_event", b"test data", id="test_binary_payload_event"),
            pytest.param(
                "test_event_with_json_schema",
                {"val1": 1, "val2": "test", "val3": {"key": "value"}, "val4": [1, 2, 3]},
                id="test_event_with_json_schema",
            ),
        ],
    )
    def test_18_sync_client_event_stream(
        self,
        thing: TestThing,
        server: RPCServer,
        action_push_events: ZMQAction,
        event_name: str,
        expected_data: Any,
    ):
        """test if event can be streamed by a synchronous threaded client"""

        resource = getattr(TestThing, event_name).to_affordance(thing)  # type: EventAffordance

        form = Form()
        form.href = server.event_publisher.socket_address
        form.contentType = "application/json"
        form.op = "subscribeevent"
        form.subprotocol = "sse"
        resource.forms = [form]
        event_client = ZMQEvent(
            resource=resource,
            logger=structlog.get_logger(),
            owner_inst=None,
        )

        event_dispatcher = getattr(thing, event_name)  # type: EventDispatcher
        assert f"{resource.thing_id}/{resource.name}" == event_dispatcher._unique_identifier

        attempts = 100
        results = []

        def cb(value: SSE):
            nonlocal results
            results.append(value)

        event_client.subscribe(cb)
        time.sleep(5)  # calm down for event publisher to connect fully as there is no handshake for events
        action_push_events(event_name=event_name, total_number_of_events=attempts)

        for i in range(attempts):
            if len(results) == attempts:
                break
            time.sleep(0.1)

        assert abs(len(results) - attempts) <= 3
        assert [res.data for res in results] == [expected_data] * len(results)
        event_client.unsubscribe()

    @pytest.mark.parametrize(
        "event_name, expected_data",
        [
            pytest.param("test_event", "test data", id="test_event"),
            pytest.param("test_binary_payload_event", b"test data", id="test_binary_payload_event"),
            pytest.param(
                "test_event_with_json_schema",
                {"val1": 1, "val2": "test", "val3": {"key": "value"}, "val4": [1, 2, 3]},
                id="test_event_with_json_schema",
            ),
        ],
    )
    async def test_19_async_client_event_stream(
        self,
        thing: TestThing,
        action_push_events: ZMQAction,
        event_name: str,
        expected_data: Any,
    ):
        """test if event can be streamed by an asynchronous client in an async loop"""
        resource = getattr(TestThing, event_name).to_affordance(thing)  # type: EventAffordance

        form = Form()
        form.href = thing.rpc_server.event_publisher.socket_address
        form.contentType = "application/json"
        form.op = "subscribeevent"
        form.subprotocol = "sse"
        resource.forms = [form]

        event_client = ZMQEvent(
            resource=resource,
            logger=structlog.get_logger(),
            owner_inst=None,
        )

        event_dispatcher = getattr(thing, event_name)  # type: EventDispatcher
        assert f"{resource.thing_id}/{resource.name}" == event_dispatcher._unique_identifier

        attempts = 100
        results = []

        def cb(value: SSE):
            nonlocal results
            # print("event callback", value)
            results.append(value)

        event_client.subscribe(cb, asynch=True)
        time.sleep(5)  # calm down for event publisher to connect fully as there is no handshake for events
        action_push_events(event_name=event_name, total_number_of_events=attempts)

        for i in range(attempts):
            if len(results) == attempts:
                break
            await asyncio.sleep(0.1)
        assert abs(len(results) - attempts) <= 3
        # since we are pushing events in multiple protocols, sometimes the event from the previous test is
        # still lingering on the socket. So the captured event must be at least the number of attempts.
        assert [res.data for res in results] == [expected_data] * len(results)
        event_client.unsubscribe()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
