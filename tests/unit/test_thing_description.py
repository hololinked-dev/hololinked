import logging

import pytest

from pydantic import BaseModel
from testkit.things import OceanOpticsSpectrometer, TestThing

from hololinked.constants import ResourceTypes
from hololinked.core.properties import Property
from hololinked.metadata.td.data_schema import DataSchema
from hololinked.metadata.td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from hololinked.utils import uuid_hex


@pytest.fixture(scope="module")
def thing():
    return OceanOpticsSpectrometer(id=f"test-thing-{uuid_hex()}", log_level=logging.ERROR)


@pytest.fixture(scope="module")
def test_thing():
    return TestThing(id=f"test-spectrometer-thing-{uuid_hex()}", log_level=logging.ERROR)


def test_01_associated_objects(thing):
    affordance = PropertyAffordance()
    affordance.objekt = OceanOpticsSpectrometer.integration_time
    affordance.owner = thing
    assert isinstance(affordance, BaseModel)
    assert isinstance(affordance, DataSchema)
    assert isinstance(affordance, InteractionAffordance)
    assert affordance.what == ResourceTypes.PROPERTY
    assert affordance.owner == thing
    assert affordance.thing_id == thing.id
    assert affordance.thing_cls == thing.__class__
    assert isinstance(affordance.objekt, Property)
    assert affordance.name == OceanOpticsSpectrometer.integration_time.name

    affordance = ActionAffordance()
    with pytest.raises(ValueError) as ex:
        affordance.objekt = OceanOpticsSpectrometer.integration_time
    with pytest.raises(TypeError) as ex:
        affordance.objekt = 5
    assert "objekt must be instance of Property, Action or Event, given type" in str(ex.value)
    affordance.objekt = OceanOpticsSpectrometer.connect
    assert affordance.what == ResourceTypes.ACTION

    affordance = EventAffordance()
    with pytest.raises(ValueError) as ex:
        affordance.objekt = OceanOpticsSpectrometer.integration_time
    with pytest.raises(TypeError) as ex:
        affordance.objekt = 5
    assert "objekt must be instance of Property, Action or Event, given type" in str(ex.value)
    affordance.objekt = OceanOpticsSpectrometer.intensity_measurement_event
    assert affordance.what == ResourceTypes.EVENT

    affordance = PropertyAffordance()
    with pytest.raises(ValueError) as ex:
        affordance.objekt = OceanOpticsSpectrometer.connect
    with pytest.raises(TypeError) as ex:
        affordance.objekt = 5
    assert "objekt must be instance of Property, Action or Event, given type" in str(ex.value)
    affordance.objekt = OceanOpticsSpectrometer.integration_time


def test_02_thing_model_generation():
    thing = TestThing(id="test-thing-model", log_level=logging.ERROR + 10)
    assert isinstance(thing.get_thing_model(skip_names=["base_property"]).json(), dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
