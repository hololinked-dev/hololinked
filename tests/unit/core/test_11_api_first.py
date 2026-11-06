import copy
import json

from inspect import getattr_static

import pytest

from testkit.things import OscilloscopeDriver, oscilloscope_TD

from hololinked.core import Action, Event, Property, Thing
from hololinked.core.interfaces import Metadata
from hololinked.core.interfaces.metadata import ConformanceError, InteractionMetadata
from hololinked.metadata.td import ThingModel
from hololinked.utils import uuid_hex


@pytest.fixture
def TD():
    return copy.deepcopy(oscilloscope_TD)


@pytest.mark.parametrize("source", ["file", "json variable"])
def test_01_load_thing_model(TD, source, tmp_path):
    if source == "file":
        path = tmp_path / "oscilloscope.td.json"
        path.write_text(json.dumps({key: value for key, value in TD.items() if key != "id"}))  # a Thing Model has no id
        model = ThingModel.from_file(str(path))
        assert (model.id, model.title) == (None, "Oscilloscope")
    else:
        model = ThingModel.from_metadata(TD)
        assert (model.id, model.title) == ("oscilloscope", "Oscilloscope")

    interactions: list[InteractionMetadata] = [
        *model.properties.values(),
        *model.actions.values(),
        *model.events.values(),
    ]

    for i in interactions:
        if i.what == "PROPERTY":
            assert i.name in TD["properties"].keys()
        elif i.what == "ACTION":
            assert i.name in TD["actions"].keys()
        elif i.what == "EVENT":
            assert i.name in TD["events"].keys()
        else:
            raise ValueError(f"Unexpected interaction kind: {i.what}, this test failed.")

    assert model.properties["time_resolution"].json() == {"type": "number", "minimum": 0}


@pytest.mark.parametrize(
    "extension",
    [
        {"properties": {"value": {"tm:ref": "other.tm.jsonld#/properties/value"}}},
        {"title": "Oscilloscope {{SERIAL}}"},
    ],
)
def test_02_thing_model_extensions_rejected(TD, extension):
    with pytest.raises(NotImplementedError, match="tm:ref"):
        ThingModel.from_metadata({**TD, **extension})


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
def test_03_compile_descriptors(TD, schema_validator: str):
    descriptors = Metadata.compile_descriptors_from(
        model=ThingModel.from_metadata(TD),
        impl=OscilloscopeDriver(),
        validator=schema_validator,
    )

    for name, descriptor in descriptors.items():
        if isinstance(descriptor, Property):
            assert name in TD["properties"].keys()
        elif isinstance(descriptor, Action):
            assert name in TD["actions"].keys()
        elif isinstance(descriptor, Event):
            assert name in TD["events"].keys()
        else:
            raise ValueError(f"Unexpected descriptor type: {type(descriptor)}, this test failed.")

    thing = type("Scope", (Thing,), descriptors)(id=f"scope-{uuid_hex()}")

    for name, descriptor in descriptors.items():
        assert getattr_static(thing, name, None) is descriptor

    # thing.time_resolution = 2.5
    # assert thing.time_resolution == 2.5
    # with pytest.raises(ValidationError):
    #     thing.time_resolution = -1
    # assert thing.channel_count == 4
    # assert thing.comment == "scope"
    # assert thing.start_acquisition.external_call(channel=2) == 2
    # with pytest.raises(ValidationError):
    #     thing.start_acquisition.external_call(channel="x")


def test_04_member_names_map_allows_name_override(TD):
    camelCaseJavascriptDocument = {
        "title": "Scope",
        "actions": {"startAcquisition": TD["actions"]["start_acquisition"]},
    }
    model = ThingModel.from_metadata(camelCaseJavascriptDocument)
    impl = OscilloscopeDriver()
    descriptors = Metadata.compile_descriptors_from(
        model=model,
        impl=impl,
        member_names_map={"startAcquisition": "start_acquisition"},
    )
    assert list(descriptors.keys()) == ["startAcquisition"]

    member_names_map = {"startAcquisition": "start_acquisition", "stop": "halt"}
    with pytest.raises(
        ConformanceError,
        match="member_names maps 'stop', which is not in the Device Description Language",
    ):
        Metadata.compile_descriptors_from(model, impl, member_names_map=member_names_map)


def test_05_allow_extra(TD):
    model = ThingModel.from_metadata(TD)
    impl = OscilloscopeDriver()
    impl.extra = Property(default=1)
    with pytest.raises(ConformanceError, match="'extra' is not in the Device Description Language"):
        Metadata.compile_descriptors_from(model, impl)
    assert "extra" not in Metadata.compile_descriptors_from(model, impl, allow_extra=True)


# def test_05_every_problem_reported_together():
#     td = {**TD, "properties": {**TD["properties"], "offset": {"type": "number"}}}
#
#     class Broken:
#         def time_resolution(self) -> float:
#             return 1.0
#
#         @property
#         def channel_count(self) -> int:
#             return 4
#
#         @channel_count.setter
#         def channel_count(self, value: int) -> None: ...
#
#         @property
#         def comment(self) -> str:
#             return "scope"
#
#         def start_acquisition(self, samples: int) -> None: ...
#
#         stop = 5
#         data_ready = Event()
#         extra = Property(default=1)
#
#     with pytest.raises(ConformanceError) as error:
#         bind(ThingModel.from_metadata(td), members_of(Broken))
#     expected = [
#         "property 'time_resolution': implemented by a function, only a @property implements a property",
#         "property 'channel_count': read-only, but the @property has a setter",
#         "property 'comment': writable, but the @property has no setter",
#         "property 'offset': property offset stores its value, it needs a default or a null option",
#         "action 'start_acquisition': start_acquisition does not match the input of action start_acquisition",
#         "action 'stop': implemented by a int, only a method implements an action",
#         "event 'data_ready': is created from the Thing Model, remove the Event named after it",
#         "Property 'extra' is not in the Thing Model, pass allow_extra=True to keep it",
#     ]
#     assert len(error.value.problems) == len(expected)
#     for problem, start in zip(error.value.problems, expected, strict=True):
#         assert problem.startswith(start)


@pytest.mark.parametrize(
    "extras, is_remote",
    [
        (
            {
                "actions": {"ping": {}, "exit": {}},
                "properties": {"state": {"type": "string", "readOnly": True}},
            },
            True,
        ),
        (
            {
                "properties": {"logger": {"type": "string"}},
                "actions": {"run_with_http_server": {}},
            },
            False,
        ),
    ],
)
def test_07_thing_builtins(TD, extras, is_remote):
    """interactions Thing implements itself are kept unless the user implements them, others clash."""
    for typ, items in extras.items():
        for name, schema in items.items():
            TD[typ][name] = schema
    model, impl = ThingModel.from_metadata(TD), OscilloscopeDriver()

    if is_remote:
        descriptors = Metadata.compile_descriptors_from(model, impl)
        assert not {name for items in extras.values() for name in items} & descriptors.keys()
    else:
        with pytest.raises(ConformanceError) as error:
            Metadata.compile_descriptors_from(model, impl)
        assert error.value.problems == [
            "property 'logger': clashes with Thing.logger",
            "action 'run_with_http_server': clashes with Thing.run_with_http_server",
        ]


# @pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
# def test_08_produce(schema_validator):
#     driver = OscilloscopeDriver()
#     thing = ThingModel.from_metadata(TD).produce(driver, id=TD["id"], validator=schema_validator)
#     assert isinstance(thing, Thing)
#     assert (type(thing).__name__, thing.id) == ("Oscilloscope", "oscilloscope")

#     thing.time_resolution = 2.5
#     with pytest.raises(ValidationError):
#         thing.time_resolution = -1
#     assert driver.written == [2.5]
#     assert thing.time_resolution == 2.5
#     assert thing.channel_count == 4
#     thing.comment = "written through"
#     assert driver.comment == "written through"

#     assert thing.start_acquisition.external_call(channel=2) == 2  # pushes before serving, dropped
#     with pytest.raises(ValidationError):
#         thing.start_acquisition.external_call(channel="x")
#     asyncio.run(thing.stop.external_call())
#     assert driver.stopped
#     assert thing.get_thing_model().title == "Oscilloscope"


# def test_09_produce_reports_conformance():
#     model = ThingModel.from_metadata(TD)

#     class NoStop:
#         time_resolution = OscilloscopeDriver.time_resolution
#         channel_count = OscilloscopeDriver.channel_count
#         start_acquisition = OscilloscopeDriver.start_acquisition

#     no_stop = NoStop()
#     with pytest.raises(ConformanceError, match="action 'stop': has no handler"):
#         model.produce(no_stop, id="scope")

#     class Broken(OscilloscopeDriver):
#         def channel_count(self) -> int:
#             return 4

#         data_ready = None

#     broken = Broken()
#     with pytest.raises(ConformanceError) as error:
#         model.produce(broken, id="scope")
#     assert error.value.problems == [
#         "property 'channel_count': implemented by a function,"
#         " only a @property, a data descriptor or a property_impl implements a property",
#         "event 'data_ready': is created from the Device Description Language, remove the NoneType named after it",
#     ]


def test_10_cannot_produce_thing_without_id(TD):
    # either file or JSON must have ID
    model = ThingModel.from_metadata({key: value for key, value in TD.items() if key != "id"})
    driver = OscilloscopeDriver()
    with pytest.raises(TypeError, match="id"):
        model.produce(driver)
    # or pass it explicitly
    assert model.produce(driver, id="scope-sim").id == "scope-sim"


# def test_11_produce_names_and_signatures():
#     """names map TD names to members; the forwarding handler keeps the signature and the request parameter."""
#     td = {
#         "id": "scope",
#         "title": "Scope",
#         "actions": {"start-acquisition": {}},
#         "properties": {"count": {"readOnly": True}},
#     }

#     class Driver:
#         @property
#         def count(self) -> int:
#             return 4

#         def acquire(self, channel: int, *, request=None) -> int:
#             return channel

#     thing = ThingModel.from_metadata(td).produce(
#         Driver(), id="scope", member_names_map={"start-acquisition": "acquire"}
#     )
#     action = type(thing).actions.descriptors["start-acquisition"]
#     assert action.request_as_argument
#     # inferred from the driver's signature, as for a code-first action
#     assert list(action.argument_schema.model_fields) == list(code_first()(Driver.acquire).argument_schema.model_fields)
#     assert getattr(thing, "start-acquisition").external_call(channel=3) == 3
#     assert thing.count == 4
#     with pytest.raises(ValueError, match="Read-only"):
#         thing.count = 5


# def test_12_produce_injects_event_emitters():
#     driver = OscilloscopeDriver()
#     thing = ThingModel.from_metadata(TD).produce(driver, id=TD["id"])
#     driver.data_ready.push([0.0])  # not served, no subscribers

#     published = []
#     thing.eventloop = SimpleNamespace(
#         event_bus=SimpleNamespace(publish=lambda topic, data: published.append((topic, data)))
#     )
#     thing.start_acquisition(channel=1)
#     assert published == [(f"{thing._qualified_id}/data_ready", [1.0, 2.0])]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
