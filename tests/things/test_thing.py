import asyncio
import threading
import time
import typing
from pydantic import BaseModel, Field

from hololinked.core import Thing, action, Property, Event
from hololinked.core.properties import (
    Number,
    String,
    Selector,
    List,
    Integer,
    ClassSelector,
)
from hololinked.core.actions import Action, BoundAction
from hololinked.param import ParameterizedFunction


class TestThing(Thing):
    @action()
    def get_transports(self):
        transports = []
        if self.rpc_server.req_rep_server is not None and self.rpc_server.req_rep_server.socket_address.startswith(
            "inproc://"
        ):
            transports.append("INPROC")
        if self.rpc_server.ipc_server is not None and self.rpc_server.ipc_server.socket_address.startswith("ipc://"):
            transports.append("IPC")
        if self.rpc_server.tcp_server is not None and self.rpc_server.tcp_server.socket_address.startswith("tcp://"):
            transports.append("TCP")
        return transports

    @action()
    def action_echo(self, value):
        # print("action_echo called with value: ", value)
        return value

    @classmethod
    def action_echo_with_classmethod(self, value):
        return value

    async def action_echo_async(self, value):
        await asyncio.sleep(0.1)
        return value

    @classmethod
    async def action_echo_async_with_classmethod(self, value):
        await asyncio.sleep(0.1)
        return value

    class parameterized_action(ParameterizedFunction):
        arg1 = Number(
            bounds=(0, 10),
            step=0.5,
            default=5,
            crop_to_bounds=True,
            doc="arg1 description",
        )
        arg2 = String(default="hello", doc="arg2 description", regex="[a-z]+")
        arg3 = ClassSelector(class_=(int, float, str), default=5, doc="arg3 description")

        def __call__(self, instance, arg1, arg2, arg3):
            return instance.id, arg1, arg2, arg3

    class parameterized_action_without_call(ParameterizedFunction):
        arg1 = Number(
            bounds=(0, 10),
            step=0.5,
            default=5,
            crop_to_bounds=True,
            doc="arg1 description",
        )
        arg2 = String(default="hello", doc="arg2 description", regex="[a-z]+")
        arg3 = ClassSelector(class_=(int, float, str), default=5, doc="arg3 description")

    class parameterized_action_async(ParameterizedFunction):
        arg1 = Number(
            bounds=(0, 10),
            step=0.5,
            default=5,
            crop_to_bounds=True,
            doc="arg1 description",
        )
        arg2 = String(default="hello", doc="arg2 description", regex="[a-z]+")
        arg3 = ClassSelector(class_=(int, float, str), default=5, doc="arg3 description")

        async def __call__(self, instance, arg1, arg2, arg3):
            await asyncio.sleep(0.1)
            return instance.id, arg1, arg2, arg3

    def __internal__(self, value):
        return value

    def incorrectly_decorated_method(self, value):
        return value

    def not_an_action(self, value):
        return value

    async def not_an_async_action(self, value):
        await asyncio.sleep(0.1)
        return value

    def json_schema_validated_action(self, val1: int, val2: str, val3: dict, val4: list):
        return {"val1": val1, "val3": val3}

    def pydantic_validated_action(
        self, val1: int, val2: str, val3: dict, val4: list
    ) -> typing.Dict[str, typing.Union[int, dict]]:
        return {"val2": val2, "val4": val4}

    @action()
    def get_serialized_data(self):
        return b"foobar"

    @action()
    def get_mixed_content_data(self):
        return "foobar", b"foobar"

    @action()
    def sleep(self):
        time.sleep(10)

    # ----------- Properties --------------

    base_property = Property(default=None, allow_None=True, doc="a base Property class")

    number_prop = Number(doc="A fully editable number property", default=1)

    string_prop = String(
        default="hello",
        regex="^[a-z]+",
        doc="A string property with a regex constraint to check value errors",
    )

    int_prop = Integer(
        default=5,
        step=2,
        bounds=(0, 100),
        doc="An integer property with step and bounds constraints to check RW",
    )

    selector_prop = Selector(objects=["a", "b", "c", 1], default="a", doc="A selector property to check RW")

    observable_list_prop = List(
        default=None,
        allow_None=True,
        observable=True,
        doc="An observable list property to check observable events on write operations",
    )

    observable_readonly_prop = Number(
        default=0,
        readonly=True,
        observable=True,
        doc="An observable readonly property to check observable events on read operations",
    )

    db_commit_number_prop = Number(
        default=0,
        db_commit=True,
        doc="A fully editable number property to check commits to db on write operations",
    )

    db_init_int_prop = Integer(
        default=1,
        db_init=True,
        doc="An integer property to check initialization from db",
    )

    db_persist_selector_prop = Selector(
        objects=["a", "b", "c", 1],
        default="a",
        db_persist=True,
        doc="A selector property to check persistence to db on write operations",
    )

    non_remote_number_prop = Number(
        default=5,
        remote=False,
        doc="A non remote number property to check non-availability on client",
    )

    sleeping_prop = Number(
        default=0,
        observable=True,
        readonly=True,
        doc="A property that sleeps for 10 seconds on read operations",
    )

    @sleeping_prop.getter
    def get_sleeping_prop(self):
        time.sleep(10)
        try:
            return self._sleeping_prop
        except AttributeError:
            return 42

    @sleeping_prop.setter
    def set_sleeping_prop(self, value):
        time.sleep(10)
        self._sleeping_prop = value

    @action()
    def set_non_remote_number_prop(self, value):
        if value < 0:
            raise ValueError("Value must be non-negative")
        self.non_remote_number_prop = value

    @action()
    def get_non_remote_number_prop(self):
        return self.non_remote_number_prop

    # ----------- Pydantic and JSON schema properties --------------

    class PydanticProp(BaseModel):
        foo: str
        bar: int
        foo_bar: float

    pydantic_prop = Property(
        default=None,
        allow_None=True,
        model=PydanticProp,
        doc="A property with a pydantic model to check RW",
    )

    pydantic_simple_prop = Property(
        default=None,
        allow_None=True,
        model="int",
        doc="A property with a simple pydantic model to check RW",
    )

    schema = {"type": "string", "minLength": 1, "maxLength": 10, "pattern": "^[a-z]+$"}

    json_schema_prop = Property(
        default=None,
        allow_None=True,
        model=schema,
        doc="A property with a json schema to check RW",
    )

    @observable_readonly_prop.getter
    def get_observable_readonly_prop(self):
        if not hasattr(self, "_observable_readonly_prop"):
            self._observable_readonly_prop = 0
        self._observable_readonly_prop += 1
        return self._observable_readonly_prop

    # ----------- Class properties --------------

    simple_class_prop = Number(class_member=True, default=42, doc="simple class property with default value")

    managed_class_prop = Number(class_member=True, doc="(managed) class property with custom getter/setter")

    @managed_class_prop.getter
    def get_managed_class_prop(cls):
        return getattr(cls, "_managed_value", 0)

    @managed_class_prop.setter
    def set_managed_class_prop(cls, value):
        if value < 0:
            raise ValueError("Value must be non-negative")
        cls._managed_value = value

    readonly_class_prop = String(class_member=True, readonly=True, doc="read-only class property")

    @readonly_class_prop.getter
    def get_readonly_class_prop(cls):
        return "read-only-value"

    deletable_class_prop = Number(
        class_member=True,
        default=100,
        doc="deletable class property with custom deleter",
    )

    @deletable_class_prop.getter
    def get_deletable_class_prop(cls):
        return getattr(cls, "_deletable_value", 100)

    @deletable_class_prop.setter
    def set_deletable_class_prop(cls, value):
        cls._deletable_value = value

    @deletable_class_prop.deleter
    def del_deletable_class_prop(cls):
        if hasattr(cls, "_deletable_value"):
            del cls._deletable_value

    not_a_class_prop = Number(class_member=False, default=43, doc="test property with class_member=False")

    @not_a_class_prop.getter
    def get_not_a_class_prop(self):
        return getattr(self, "_not_a_class_value", 43)

    @not_a_class_prop.setter
    def set_not_a_class_prop(self, value):
        self._not_a_class_value = value

    @not_a_class_prop.deleter
    def del_not_a_class_prop(self):
        if hasattr(self, "_not_a_class_value"):
            del self._not_a_class_value

    @action()
    def print_props(self):
        print(f"number_prop: {self.number_prop}")
        print(f"string_prop: {self.string_prop}")
        print(f"int_prop: {self.int_prop}")
        print(f"selector_prop: {self.selector_prop}")
        print(f"observable_list_prop: {self.observable_list_prop}")
        print(f"observable_readonly_prop: {self.observable_readonly_prop}")
        print(f"db_commit_number_prop: {self.db_commit_number_prop}")
        print(f"db_init_int_prop: {self.db_init_int_prop}")
        print(f"db_persist_selctor_prop: {self.db_persist_selector_prop}")
        print(f"non_remote_number_prop: {self.non_remote_number_prop}")

    # ----------- Events --------------

    test_event = Event(doc="test event with arbitrary payload")

    total_number_of_events = Number(default=100, bounds=(1, None), doc="Total number of events pushed")

    @action()
    def push_events(self, event_name: str = "test_event", total_number_of_events: int = 100):
        if event_name not in self.events:
            raise ValueError(f"Event {event_name} is not a valid event")
        threading.Thread(target=self._push_worker, args=(event_name, total_number_of_events)).start()

    def _push_worker(self, event_name: str = "test_event", total_number_of_events: int = 100):
        for i in range(total_number_of_events):
            event_descriptor = self.events.descriptors[event_name]
            if event_descriptor == self.__class__.test_event:
                # print(f"pushing event {event_name} with value {i}")
                self.test_event.push("test data")
            elif event_descriptor == self.__class__.test_binary_payload_event:
                # print(f"pushing event {event_name} with value {i}")
                self.test_binary_payload_event.push(b"test data")
            elif event_descriptor == self.__class__.test_mixed_content_payload_event:
                # print(f"pushing event {event_name} with value {i}")
                self.test_mixed_content_payload_event.push(("test data", b"test data"))
            elif event_descriptor == self.__class__.test_event_with_json_schema:
                # print(f"pushing event {event_name} with value {i}")
                self.test_event_with_json_schema.push(
                    {
                        "val1": 1,
                        "val2": "test",
                        "val3": {"key": "value"},
                        "val4": [1, 2, 3],
                    }
                )
            elif event_descriptor == self.test_event_with_pydantic_schema:
                self.test_event_with_pydantic_schema.push(
                    {
                        "val1": 1,
                        "val2": "test",
                        "val3": {"key": "value"},
                        "val4": [1, 2, 3],
                    }
                )
            time.sleep(0.01)  # 10ms

    test_binary_payload_event = Event(doc="test event with binary payload")

    test_mixed_content_payload_event = Event(doc="test event with mixed content payload")

    test_event_with_json_schema = Event(doc="test event with schema validation")

    test_event_with_pydantic_schema = Event(doc="test event with pydantic schema validation")

    # --- Examples from existing device implementations

    # ---------- Picoscope

    analog_offset_input_schema = {
        "type": "object",
        "properties": {
            "voltage_range": {
                "type": "string",
                "enum": [
                    "10mV",
                    "20mV",
                    "50mV",
                    "100mV",
                    "200mV",
                    "500mV",
                    "1V",
                    "2V",
                    "5V",
                    "10V",
                    "20V",
                    "50V",
                    "MAX_RANGES",
                ],
            },
            "coupling": {"type": "string", "enum": ["AC", "DC"]},
        },
    }

    analog_offset_output_schema = {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "items": {
            "type": "number",
        },
    }

    @action(
        input_schema=analog_offset_input_schema,
        output_schema=analog_offset_output_schema,
    )
    def get_analogue_offset(self, voltage_range: str, coupling: str) -> typing.Tuple[float, float]:
        """analogue offset for a voltage range and coupling"""
        print(f"get_analogue_offset called with voltage_range={voltage_range}, coupling={coupling}")
        return 0.0, 0.0

    set_channel_schema = {
        "type": "object",
        "properties": {
            "channel": {"type": "string", "enum": ["A", "B", "C", "D"]},
            "enabled": {"type": "boolean"},
            "voltage_range": {
                "type": "string",
                "enum": [
                    "10mV",
                    "20mV",
                    "50mV",
                    "100mV",
                    "200mV",
                    "500mV",
                    "1V",
                    "2V",
                    "5V",
                    "10V",
                    "20V",
                    "50V",
                    "MAX_RANGES",
                ],
            },
            "offset": {"type": "number"},
            "coupling": {"type": "string", "enum": ["AC", "DC"]},
            "bw_limiter": {"type": "string", "enum": ["full", "20MHz"]},
        },
    }

    @action(input_schema=set_channel_schema)
    def set_channel(
        self,
        channel: str,
        enabled: bool = True,
        v_range: str = "2V",
        offset: float = 0,
        coupling: str = "DC_1M",
        bw_limiter: str = "full",
    ) -> None:
        """
        Set the parameter for a channel.
        https://www.picotech.com/download/manuals/picoscope-6000-series-a-api-programmers-guide.pdf
        """
        print(
            f"set_channel called with channel={channel}, enabled={enabled}, "
            + f"v_range={v_range}, offset={offset}, coupling={coupling}, bw_limiter={bw_limiter}"
        )

    @action()
    def set_channel_pydantic(
        self,
        channel: typing.Literal["A", "B", "C", "D"],
        enabled: bool = True,
        v_range: typing.Literal[
            "10mV",
            "20mV",
            "50mV",
            "100mV",
            "200mV",
            "500mV",
            "1V",
            "2V",
            "5V",
            "10V",
            "20V",
            "50V",
            "MAX_RANGES",
        ] = "2V",
        offset: float = 0,
        coupling: typing.Literal["AC", "DC"] = "DC_1M",
        bw_limiter: typing.Literal["full", "20MHz"] = "full",
    ) -> None:
        """
        Set the parameter for a channel.
        https://www.picotech.com/download/manuals/picoscope-6000-series-a-api-programmers-guide.pdf
        """
        print(
            f"set_channel_pydantic called with channel={channel}, enabled={enabled}, "
            + f"v_range={v_range}, offset={offset}, coupling={coupling}, bw_limiter={bw_limiter}"
        )

    # ---- Gentec Optical Energy Meter

    @action(input_schema={"type": "string", "enum": ["QE25LP-S-MB", "QE12LP-S-MB-QED-D0"]})
    def set_sensor_model(self, value: str):
        """
        Set the attached sensor to the meter under control.
        Sensor should be defined as a class and added to the AllowedSensors dict.
        """
        print(f"set_sensor_model called with value={value}")

    @action()
    def set_sensor_model_pydantic(self, value: typing.Literal["QE25LP-S-MB", "QE12LP-S-MB-QED-D0"]):
        """
        Set the attached sensor to the meter under control.
        Sensor should be defined as a class and added to the AllowedSensors dict.
        """
        print(f"set_sensor_model_pydantic called with value={value}")

    @action()
    def start_acquisition(self, max_count: typing.Annotated[int, Field(gt=0)]):
        """
        Start acquisition of energy measurements.

        Parameters
        ----------
        max_count: int
            maximum number of measurements to acquire before stopping automatically.
        """
        print(f"start_acquisition called with max_count={max_count}")

    data_point_event_schema = {
        "type": "object",
        "properties": {"timestamp": {"type": "string"}, "energy": {"type": "number"}},
        "required": ["timestamp", "energy"],
    }

    data_point_event = Event(
        doc="Event raised when a new data point is available",
        label="Data Point Event",
        schema=data_point_event_schema,
    )

    # ----- Serial Utility
    @action()
    def execute_instruction(self, command: str, return_data_size: typing.Annotated[int, Field(ge=0)] = 0) -> str:
        """
        executes instruction given by the ASCII string parameter 'command'.
        If return data size is greater than 0, it reads the response and returns the response.
        Return Data Size - in bytes - 1 ASCII character = 1 Byte.
        """
        print(f"execute_instruction called with command={command}, return_data_size={return_data_size}")
        return b""


def replace_methods_with_actions(thing_cls: typing.Type[TestThing]) -> None:
    exposed_actions = []
    if not isinstance(thing_cls.action_echo, (Action, BoundAction)):
        thing_cls.action_echo = action()(thing_cls.action_echo)
        thing_cls.action_echo.__set_name__(thing_cls, "action_echo")
    exposed_actions.append("action_echo")

    if not isinstance(thing_cls.action_echo_with_classmethod, (Action, BoundAction)):
        # classmethod can be decorated with action
        thing_cls.action_echo_with_classmethod = action()(thing_cls.action_echo_with_classmethod)
        # BoundAction already, cannot call __set_name__ on it, at least at the time of writing
    exposed_actions.append("action_echo_with_classmethod")

    if not isinstance(thing_cls.action_echo_async, (Action, BoundAction)):
        # async methods can be decorated with action
        thing_cls.action_echo_async = action()(thing_cls.action_echo_async)
        thing_cls.action_echo_async.__set_name__(thing_cls, "action_echo_async")
    exposed_actions.append("action_echo_async")

    if not isinstance(thing_cls.action_echo_async_with_classmethod, (Action, BoundAction)):
        # async classmethods can be decorated with action
        thing_cls.action_echo_async_with_classmethod = action()(thing_cls.action_echo_async_with_classmethod)
        # BoundAction already, cannot call __set_name__ on it, at least at the time of writing
    exposed_actions.append("action_echo_async_with_classmethod")

    if not isinstance(thing_cls.parameterized_action, (Action, BoundAction)):
        # parameterized function can be decorated with action
        thing_cls.parameterized_action = action(safe=True)(thing_cls.parameterized_action)
        thing_cls.parameterized_action.__set_name__(thing_cls, "parameterized_action")
    exposed_actions.append("parameterized_action")

    if not isinstance(thing_cls.parameterized_action_without_call, (Action, BoundAction)):
        thing_cls.parameterized_action_without_call = action(idempotent=True)(
            thing_cls.parameterized_action_without_call
        )
        thing_cls.parameterized_action_without_call.__set_name__(thing_cls, "parameterized_action_without_call")
    exposed_actions.append("parameterized_action_without_call")

    if not isinstance(thing_cls.parameterized_action_async, (Action, BoundAction)):
        thing_cls.parameterized_action_async = action(synchronous=True)(thing_cls.parameterized_action_async)
        thing_cls.parameterized_action_async.__set_name__(thing_cls, "parameterized_action_async")
    exposed_actions.append("parameterized_action_async")

    if not isinstance(thing_cls.json_schema_validated_action, (Action, BoundAction)):
        # schema validated actions
        thing_cls.json_schema_validated_action = action(
            input_schema={
                "type": "object",
                "properties": {
                    "val1": {"type": "integer"},
                    "val2": {"type": "string"},
                    "val3": {"type": "object"},
                    "val4": {"type": "array"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {"val1": {"type": "integer"}, "val3": {"type": "object"}},
            },
        )(thing_cls.json_schema_validated_action)
        thing_cls.json_schema_validated_action.__set_name__(thing_cls, "json_schema_validated_action")
    exposed_actions.append("json_schema_validated_action")

    if not isinstance(thing_cls.pydantic_validated_action, (Action, BoundAction)):
        thing_cls.pydantic_validated_action = action()(thing_cls.pydantic_validated_action)
        thing_cls.pydantic_validated_action.__set_name__(thing_cls, "pydantic_validated_action")
    exposed_actions.append("pydantic_validated_action")

    replace_methods_with_actions._exposed_actions = exposed_actions


test_thing_TD = {
    "title": "TestThing",
    "id": "test-thing",
    "actions": {
        "get_transports": {
            "title": "get_transports",
            "description": "returns available transports",
        },
        "action_echo": {
            "title": "action_echo",
            "description": "returns value as it is to the client",
        },
        "get_serialized_data": {
            "title": "get_serialized_data",
            "description": "returns serialized data",
        },
        "get_mixed_content_data": {
            "title": "get_mixed_content_data",
            "description": "returns mixed content data",
        },
        "sleep": {
            "title": "sleep",
            "description": "sleeps for 10 seconds",
        },
        "push_events": {
            "title": "push_events",
            "description": "pushes events",
        },
    },
    "properties": {
        "base_property": {
            "title": "base_property",
            "description": "test property",
            "default": None,
        },
        "number_prop": {
            "title": "number_prop",
            "description": "A fully editable number property",
            "default": 0,
        },
        "string_prop": {
            "title": "string_prop",
            "description": "A string property with a regex constraint to check value errors",
            "default": "hello",
            "regex": "^[a-z]+$",
        },
        "total_number_of_events": {
            "title": "total_number_of_events",
            "description": "Total number of events pushed",
            "default": 100,
            "minimum": 1,
        },
        "json_schema_prop": {
            "title": "json_schema_prop",
            "description": "A property with a json schema to check RW",
            "type": "string",
            "minLength": 1,
            "maxLength": 10,
            "pattern": "^[a-z]+$",
        },
        "pydantic_prop": {
            "title": "pydantic_prop",
            "description": "A property with a pydantic schema to check RW",
        },  # actually the data schema is not necessary to trigger an execution on the server, so we are skipping it temporarily
        "pydantic_simple_prop": {
            "title": "pydantic_simple_prop",
            "description": "A property with a simple pydantic schema to check RW",
        },  # actually the data schema is not necessary to trigger an execution on the server, so we are skipping it temporarily
    },
    "events": {
        "test_event": {"title": "test_event", "description": "test event"},
        "test_binary_payload_event": {
            "title": "test_binary_payload_event",
            "description": "test event with binary payload",
        },
        "test_mixed_content_payload_event": {
            "title": "test_mixed_content_payload_event",
            "description": "test event with mixed content payload",
        },
        "test_event_with_json_schema": {
            "title": "test_event_with_json_schema",
            "description": "test event with schema validation",
            "data": {
                "val1": {"type": "integer", "description": "integer value"},
                "val2": {"type": "string", "description": "string value"},
                "val3": {"type": "object", "description": "object value"},
                "val4": {"type": "array", "description": "array value"},
            },
        },
        "test_event_with_pydantic_schema": {
            "title": "test_event_with_pydantic_schema",
            "description": "test event with pydantic schema validation",
        },
    },
}


if __name__ == "__main__":
    T = TestThing(id="test-thing")
    T.run()
