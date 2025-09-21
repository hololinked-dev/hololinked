import unittest

from hololinked.serializers import Serializers
from hololinked.serializers.serializers import BaseSerializer

try:
    from .utils import TestRunner, TestCase
    from .things import TestThing
except ImportError:
    from utils import TestRunner, TestCase
    from things import TestThing


class TestSerializer(TestCase):
    """Test the Serializers class"""

    # test register a new serializer with content type
    class YAMLSerializer(BaseSerializer):
        """just a dummy, does not really serialize to YAML"""

        @property
        def content_type(self):
            return "application/yaml"

    def test_1_singleton(self):
        """Test the singleton nature of the Serializers class."""

        serializers = Serializers()
        self.assertEqual(serializers, Serializers())
        self.assertNotEqual(Serializers, Serializers())
        self.assertIsInstance(serializers, Serializers)
        # all are class attributes
        self.assertEqual(serializers.json, Serializers.json)
        self.assertEqual(serializers.pickle, Serializers.pickle)
        self.assertEqual(serializers.msgpack, Serializers.msgpack)
        self.assertEqual(serializers.content_types, Serializers.content_types)
        self.assertEqual(serializers.object_content_type_map, Serializers.object_content_type_map)
        self.assertEqual(serializers.object_serializer_map, Serializers.object_serializer_map)
        self.assertEqual(serializers.protocol_serializer_map, Serializers.protocol_serializer_map)
        # check existing serializers are all instances of BaseSerializer
        for name, serializer in Serializers.content_types.items():
            self.assertIsInstance(serializer, BaseSerializer)
        # check default serializer, given that we know its JSON at least for the current test
        self.assertEqual(serializers.default, Serializers.json)
        self.assertEqual(serializers.default, Serializers.default)
        self.assertEqual(serializers.default, Serializers().json)
        self.assertEqual(serializers.default, Serializers().default)
        # check default content type, given that we know its JSON at least for the current test
        self.assertEqual(serializers.default_content_type, Serializers.json.content_type)
        # change default to pickle and check if it is set correctly
        # serializers.default = serializers.pickle
        # self.assertEqual(serializers.default, Serializers.pickle)
        # self.assertEqual(Serializers().default, Serializers.pickle)

    def test_2_protocol_registration(self):
        """i.e. test if a new serializer (protocol) can be registered"""

        # get existing number of serializers
        num_serializers = len(Serializers.content_types)

        # test register a new serializer
        base_serializer = BaseSerializer()
        # register with name
        self.assertWarns(UserWarning, Serializers.register, base_serializer, "base")
        # user warning because content type property is not defined
        # above is same as Serializers.register(base_serializer, 'base')

        # check if name became a class attribute and name can be accessed as an attribute
        self.assertIn("base", Serializers)
        self.assertEqual(Serializers.base, base_serializer)
        self.assertEqual(Serializers().base, base_serializer)
        # we dont support getitem at instance level yet so we cannot test assertIn

        # since a content type is not set, it should not be in the content types
        self.assertNotIn(base_serializer, Serializers.content_types.values())
        # so the length of content types should be the same
        self.assertEqual(len(Serializers.content_types), num_serializers)

        # instantiate
        yaml_serializer = self.YAMLSerializer()
        # register with name
        Serializers.register(yaml_serializer, "yaml")
        # check if name became a class attribute and name can be accessed as an attribute
        self.assertIn("yaml", Serializers)
        self.assertEqual(Serializers.yaml, yaml_serializer)
        self.assertEqual(Serializers().yaml, yaml_serializer)
        # we dont support getitem at instance level yet

        # since a content type is set, it should be in the content types
        self.assertIn(yaml_serializer.content_type, Serializers.content_types.keys())
        self.assertIn(yaml_serializer, Serializers.content_types.values())
        # so the length of content types should have increased by 1
        self.assertEqual(len(Serializers.content_types), num_serializers + 1)

    def test_3_registration_for_objects(self):
        """i.e. test if a new serializer can be registered for a specific property, action or event"""
        Serializers.register_content_type_for_object(TestThing.base_property, "application/x-pickle")
        Serializers.register_content_type_for_object(TestThing.action_echo, "application/msgpack")
        Serializers.register_content_type_for_object(TestThing.test_event, "application/yaml")

        self.assertEqual(
            Serializers.for_object(None, "TestThing", "action_echo"),
            Serializers.msgpack,
        )
        self.assertEqual(
            Serializers.for_object(None, "TestThing", "base_property"),
            Serializers.pickle,
        )
        self.assertEqual(Serializers.for_object(None, "TestThing", "test_event"), Serializers.yaml)
        self.assertEqual(
            Serializers.for_object(None, "TestThing", "test_unknown_property"),
            Serializers.default,
        )

    def test_4_registration_for_objects_by_name(self):
        Serializers.register_content_type_for_object_per_thing_instance(
            "test_thing", "base_property", "application/yaml"
        )
        self.assertIsInstance(
            Serializers.for_object("test_thing", None, "base_property"),
            self.YAMLSerializer,
        )

    def test_5_registration_dict(self):
        """test the dictionary where all serializers are stored"""
        # depends on test 3
        self.assertIn("test_thing", Serializers.object_content_type_map)
        self.assertIn("base_property", Serializers.object_content_type_map["test_thing"])
        self.assertEqual(
            Serializers.object_content_type_map["test_thing"]["base_property"],
            "application/yaml",
        )

        self.assertIn("action_echo", Serializers.object_content_type_map["TestThing"])
        self.assertEqual(
            Serializers.object_content_type_map["TestThing"]["action_echo"],
            "application/msgpack",
        )
        self.assertIn("test_event", Serializers.object_content_type_map["TestThing"])
        self.assertEqual(
            Serializers.object_content_type_map["TestThing"]["test_event"],
            "application/yaml",
        )

    def test_6_retrieval(self):
        # added in previous tests
        self.assertIsInstance(
            Serializers.for_object("test_thing", None, "base_property"),
            self.YAMLSerializer,
        )
        # unknown object should retrieve the default serializer
        self.assertEqual(
            Serializers.for_object("test_thing", None, "test_unknown_property"),
            Serializers.default,
        )
        # unknown thing should retrieve the default serializer
        self.assertEqual(
            Serializers.for_object("test_unknown_thing", None, "base_property"),
            Serializers.default,
        )

    def test_7_set_default(self):
        """test setting the default serializer"""
        # get existing default
        old_default = Serializers.default
        # set new default and check if default is set
        Serializers.default = Serializers.yaml
        self.assertEqual(Serializers.default, Serializers.yaml)
        self.test_6_retrieval()  # check if retrieval is consistent with default
        # reset default and check if default is reset
        Serializers.default = old_default
        self.assertEqual(Serializers.default, old_default)
        self.assertEqual(Serializers.default, Serializers.json)  # because we know its JSON

    @classmethod
    def tearDownClass(cls):
        Serializers.reset()
        return super().tearDownClass()


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())
