import logging, unittest, tempfile, os
from hololinked.core.properties import Number
from hololinked.storage.database import BaseDB

try:
    from .utils import TestCase, TestRunner
    from .things import TestThing
except ImportError:
    from utils import TestCase, TestRunner
    from things import TestThing


class TestProperty(TestCase):

    def test_01_simple_class_property(self):
        """Test basic class property functionality"""
        # Test class-level access
        self.assertEqual(TestThing.simple_class_prop, 42)
        TestThing.simple_class_prop = 100
        self.assertEqual(TestThing.simple_class_prop, 100)

        # Test that instance-level access reflects class value
        instance1 = TestThing(id="test1", log_level=logging.WARN)
        instance2 = TestThing(id="test2", log_level=logging.WARN)
        self.assertEqual(instance1.simple_class_prop, 100)
        self.assertEqual(instance2.simple_class_prop, 100)

        # Test that instance-level changes affect class value
        instance1.simple_class_prop = 200
        self.assertEqual(TestThing.simple_class_prop, 200)
        self.assertEqual(instance2.simple_class_prop, 200)

    def test_02_managed_class_property(self):
        """Test class property with custom getter/setter"""
        # Test initial value
        self.assertEqual(TestThing.managed_class_prop, 0)
        # Test valid value assignment
        TestThing.managed_class_prop = 50
        self.assertEqual(TestThing.managed_class_prop, 50)
        # Test validation in setter
        with self.assertRaises(ValueError):
            TestThing.managed_class_prop = -10
        # Verify value wasn't changed after failed assignment
        self.assertEqual(TestThing.managed_class_prop, 50)
        # Test instance-level validation
        instance = TestThing(id="test3", log_level=logging.WARN)
        with self.assertRaises(ValueError):
            instance.managed_class_prop = -20
        # Test that instance-level access reflects class value
        self.assertEqual(instance.managed_class_prop, 50)
        # Test that instance-level changes affects class value
        instance.managed_class_prop = 100
        self.assertEqual(TestThing.managed_class_prop, 100)
        self.assertEqual(instance.managed_class_prop, 100)

    def test_03_readonly_class_property(self):
        """Test read-only class property behavior"""
        # Test reading the value
        self.assertEqual(TestThing.readonly_class_prop, "read-only-value")

        # Test that setting raises an error at class level
        with self.assertRaises(ValueError):
            TestThing.readonly_class_prop = "new-value"

        # Test that setting raises an error at instance level
        instance = TestThing(id="test4", log_level=logging.WARN)
        with self.assertRaises(ValueError):
            instance.readonly_class_prop = "new-value"

        # Verify value remains unchanged
        self.assertEqual(TestThing.readonly_class_prop, "read-only-value")
        self.assertEqual(instance.readonly_class_prop, "read-only-value")

    def test_04_deletable_class_property(self):
        """Test class property deletion"""
        # Test initial value
        self.assertEqual(TestThing.deletable_class_prop, 100)

        # Test setting new value
        TestThing.deletable_class_prop = 150
        self.assertEqual(TestThing.deletable_class_prop, 150)

        # Test deletion
        instance = TestThing(id="test5", log_level=logging.WARN)
        del TestThing.deletable_class_prop
        self.assertEqual(TestThing.deletable_class_prop, 100)  # Should return to default
        self.assertEqual(instance.deletable_class_prop, 100)

        # Test instance-level deletion
        instance.deletable_class_prop = 200
        self.assertEqual(TestThing.deletable_class_prop, 200)
        del instance.deletable_class_prop
        self.assertEqual(TestThing.deletable_class_prop, 100)  # Should return to default

    def test_05_descriptor_access(self):
        """Test descriptor access for class properties"""
        # Test direct access through descriptor
        instance = TestThing(id="test6", log_level=logging.WARN)
        self.assertIsInstance(TestThing.not_a_class_prop, Number)
        self.assertEqual(instance.not_a_class_prop, 43)
        instance.not_a_class_prop = 50
        self.assertEqual(instance.not_a_class_prop, 50)

        del instance.not_a_class_prop
        # deleter deletes only an internal instance variable
        self.assertTrue(hasattr(TestThing, "not_a_class_prop"))
        self.assertEqual(instance.not_a_class_prop, 43)

        del TestThing.not_a_class_prop
        # descriptor itself is deleted
        self.assertFalse(hasattr(TestThing, "not_a_class_prop"))
        self.assertFalse(hasattr(instance, "not_a_class_prop"))
        with self.assertRaises(AttributeError):
            instance.not_a_class_prop

    def _generate_db_ops_tests(self) -> None:
        def test_prekill(thing: TestThing) -> None:
            self.assertEqual(thing.db_commit_number_prop, 0)
            thing.db_commit_number_prop = 100
            self.assertEqual(thing.db_commit_number_prop, 100)
            self.assertEqual(thing.db_engine.get_property("db_commit_number_prop"), 100)

            # test db persist property
            self.assertEqual(thing.db_persist_selector_prop, "a")
            thing.db_persist_selector_prop = "c"
            self.assertEqual(thing.db_persist_selector_prop, "c")
            self.assertEqual(thing.db_engine.get_property("db_persist_selector_prop"), "c")

            # test db init property
            self.assertEqual(thing.db_init_int_prop, 1)
            thing.db_init_int_prop = 50
            self.assertEqual(thing.db_init_int_prop, 50)
            self.assertNotEqual(thing.db_engine.get_property("db_init_int_prop"), 50)
            self.assertEqual(
                thing.db_engine.get_property("db_init_int_prop"),
                TestThing.db_init_int_prop.default,
            )
            del thing

        def test_postkill(thing: TestThing) -> None:
            # deleted thing and reload from database
            self.assertEqual(thing.db_init_int_prop, TestThing.db_init_int_prop.default)
            self.assertEqual(thing.db_persist_selector_prop, "c")
            self.assertNotEqual(thing.db_commit_number_prop, 100)
            self.assertEqual(thing.db_commit_number_prop, TestThing.db_commit_number_prop.default)

        return test_prekill, test_postkill

    def test_06_sqlalchemy_db_operations(self):
        """Test SQLAlchemy database operations"""
        thing_id = "test-db-operations"
        file_path = f"{BaseDB.get_temp_dir_for_class_name(TestThing.__name__)}/{thing_id}.db"
        try:
            os.remove(file_path)
        except (OSError, FileNotFoundError):
            pass
        self.assertTrue(not os.path.exists(file_path))

        test_prekill, test_postkill = self._generate_db_ops_tests()

        thing = TestThing(id=thing_id, use_default_db=True, log_level=logging.WARN)
        test_prekill(thing)

        thing = TestThing(id=thing_id, use_default_db=True, log_level=logging.WARN)
        test_postkill(thing)

    def test_07_json_db_operations(self):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            filename = tf.name

        thing_id = "test-db-operations-json"
        test_prekill, test_postkill = self._generate_db_ops_tests()

        thing = TestThing(
            id=thing_id,
            use_json_file=True,
            json_filename=filename,
            log_level=logging.WARN,
        )
        test_prekill(thing)

        thing = TestThing(
            id=thing_id,
            use_json_file=True,
            json_filename=filename,
            log_level=logging.WARN,
        )
        test_postkill(thing)

        os.remove(filename)


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())
