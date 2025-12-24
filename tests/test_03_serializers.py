import pytest

from things import TestThing

from hololinked.serializers import Serializers
from hololinked.serializers.serializers import BaseSerializer


class YAMLSerializer(BaseSerializer):
    """just a dummy, does not really serialize to YAML"""

    @property
    def content_type(self):
        return "application/yaml"


@pytest.fixture(scope="module")
def yaml_serializer() -> BaseSerializer:
    # test register a new serializer with content type
    return YAMLSerializer()


def test_01_singleton():
    """Test the singleton nature of the Serializers class."""

    serializers = Serializers()
    assert serializers == Serializers()
    assert Serializers != Serializers()
    assert isinstance(serializers, Serializers)
    # all are class attributes
    assert serializers.json == Serializers.json
    assert serializers.pickle == Serializers.pickle
    assert serializers.msgpack == Serializers.msgpack
    assert serializers.content_types == Serializers.content_types
    assert serializers.object_content_type_map == Serializers.object_content_type_map
    assert serializers.object_serializer_map == Serializers.object_serializer_map
    assert serializers.protocol_serializer_map == Serializers.protocol_serializer_map
    # check existing serializers are all instances of BaseSerializer
    for name, serializer in Serializers.content_types.items():
        assert isinstance(serializer, BaseSerializer)
    # check default serializer, given that we know its JSON at least for the current test
    assert serializers.default == Serializers.json
    assert serializers.default == Serializers.default
    assert serializers.default == Serializers().json
    assert serializers.default == Serializers().default
    # check default content type, given that we know its JSON at least for the current test
    assert serializers.default_content_type == Serializers.json.content_type
    # change default to pickle and check if it is set correctly
    # serializers.default = serializers.pickle
    # self.assertEqual(serializers.default, Serializers.pickle)
    # self.assertEqual(Serializers().default, Serializers.pickle)


def test_02_protocol_registration(yaml_serializer: BaseSerializer):
    """i.e. test if a new serializer (protocol) can be registered"""

    # get existing number of serializers
    num_serializers = len(Serializers.content_types)

    # test register a new serializer
    base_serializer = BaseSerializer()
    # register with name
    with pytest.warns(UserWarning):
        Serializers.register(base_serializer, "base")
    # user warning because content type property is not defined
    # above is same as Serializers.register(base_serializer, 'base')

    # check if name became a class attribute and name can be accessed as an attribute
    assert "base" in Serializers
    assert Serializers.base == base_serializer
    assert Serializers().base == base_serializer
    # we dont support getitem at instance level yet so we cannot test assertIn

    # since a content type is not set, it should not be in the content types
    assert base_serializer not in Serializers.content_types.values()
    # so the length of content types should be the same
    assert len(Serializers.content_types) == num_serializers

    # register with name
    Serializers.register(yaml_serializer, "yaml")
    # check if name became a class attribute and name can be accessed as an attribute
    assert "yaml" in Serializers
    assert Serializers.yaml == yaml_serializer
    assert Serializers().yaml == yaml_serializer
    # we dont support getitem at instance level yet

    # since a content type is set, it should be in the content types
    assert yaml_serializer.content_type in Serializers.content_types.keys()
    assert yaml_serializer in Serializers.content_types.values()
    # so the length of content types should have increased by 1
    assert len(Serializers.content_types) == num_serializers + 1


def test_03_registration_for_objects():
    """i.e. test if a new serializer can be registered for a specific property, action or event"""
    Serializers.register_content_type_for_object(TestThing.base_property, "application/x-pickle")
    Serializers.register_content_type_for_object(TestThing.action_echo, "application/msgpack")
    Serializers.register_content_type_for_object(TestThing.test_event, "application/yaml")

    assert Serializers.for_object(None, "TestThing", "action_echo") == Serializers.msgpack
    assert Serializers.for_object(None, "TestThing", "base_property") == Serializers.pickle
    assert Serializers.for_object(None, "TestThing", "test_event") == Serializers.yaml
    assert Serializers.for_object(None, "TestThing", "test_unknown_property") == Serializers.default


def test_04_registration_for_objects_by_name():
    Serializers.register_content_type_for_object_per_thing_instance("test_thing", "base_property", "application/yaml")
    assert isinstance(Serializers.for_object("test_thing", None, "base_property"), YAMLSerializer)


def test_05_registration_dict():
    """test the dictionary where all serializers are stored"""
    # depends on test 3
    assert "test_thing" in Serializers.object_content_type_map
    assert "base_property" in Serializers.object_content_type_map["test_thing"]
    assert Serializers.object_content_type_map["test_thing"]["base_property"] == "application/yaml"
    assert Serializers.object_content_type_map["test_thing"]["base_property"] == "application/yaml"

    assert "action_echo" in Serializers.object_content_type_map["TestThing"]
    assert Serializers.object_content_type_map["TestThing"]["action_echo"] == "application/msgpack"
    assert "test_event" in Serializers.object_content_type_map["TestThing"]
    assert Serializers.object_content_type_map["TestThing"]["test_event"] == "application/yaml"


def test_06_retrieval():
    # added in previous tests
    assert isinstance(Serializers.for_object("test_thing", None, "base_property"), YAMLSerializer)
    # unknown object should retrieve the default serializer
    assert Serializers.for_object("test_thing", None, "test_unknown_property") == Serializers.default
    # unknown thing should retrieve the default serializer
    assert Serializers.for_object("test_unknown_thing", None, "base_property") == Serializers.default


def test_07_set_default():
    """test setting the default serializer"""
    # get existing default
    old_default = Serializers.default
    # set new default and check if default is set
    Serializers.default = Serializers.yaml
    assert Serializers.default == Serializers.yaml
    test_06_retrieval()  # check if retrieval is consistent with default
    # reset default and check if default is reset
    Serializers.default = old_default
    assert Serializers.default == old_default
    assert Serializers.default == Serializers.json  # because we know its JSON


def test_08_unknown_content_types():
    """test registration of unknown content types for objects"""
    Serializers.register_content_type_for_object(TestThing.number_prop, "application/unknown")
    assert Serializers.for_object(None, "TestThing", "number_prop") is None
    assert Serializers.get_content_type_for_object(None, "TestThing", "number_prop") == "application/unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
