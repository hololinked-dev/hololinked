import logging
import unittest
import tempfile
import os
import json
import copy
import pydantic

from hololinked.core.properties import Number
from hololinked.storage.database import BaseDB, ThingDB
from hololinked.serializers import PythonBuiltinJSONSerializer

try:
    from .utils import TestCase, TestRunner
    from .things import TestThing
except ImportError:
    from utils import TestCase, TestRunner
    from things import TestThing


class TestProperty(TestCase):

    def notest_01_simple_class_property(self):
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

    def notest_02_managed_class_property(self):
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

    def notest_03_readonly_class_property(self):
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

    def notest_04_deletable_class_property(self):
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

    def notest_05_descriptor_access(self):
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

    def _test_06_sqlalchemy_db_operations(self):
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

    def _test_07_json_db_operations(self):
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

    def test_08_db_config(self):
        """Test database configuration options"""
        thing = TestThing(id="test-sql-config", log_level=logging.WARN)

        # ----- SQL config tests -----
        sql_db_config = {
            "provider": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "hololinked",
            "user": "hololinked",
            "password": "postgresnonadminpassword",
        }
        with open("test_sql_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(sql_db_config, f)

        # correct config
        ThingDB(thing, config_file="test_sql_config.json")
        # foreign field
        sql_db_config_2 = copy.deepcopy(sql_db_config)
        sql_db_config_2["passworda"] = "postgresnonadminpassword"
        with open("test_sql_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(sql_db_config_2, f)
        self.assertRaises(
            pydantic.ValidationError,
            ThingDB,
            thing,
            config_file="test_sql_config.json",
        )
        # missing field
        sql_db_config_3 = copy.deepcopy(sql_db_config)
        sql_db_config_3.pop("password")
        with open("test_sql_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(sql_db_config_3, f)
        self.assertRaises(
            ValueError,
            ThingDB,
            thing,
            config_file="test_sql_config.json",
        )
        # URI instead of other fields
        sql_db_config = dict(
            provider="postgresql",
            uri="postgresql://hololinked:postgresnonadminpassword@localhost:5432/hololinked",
        )
        with open("test_sql_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(sql_db_config, f)
        ThingDB(thing, config_file="test_sql_config.json")

        os.remove("test_sql_config.json")

        # ----- MongoDB config tests -----
        mongo_db_config = {
            "provider": "mongo",
            "host": "localhost",
            "port": 27017,
            "database": "hololinked",
            "user": "hololinked",
            "password": "mongononadminpassword",
            "authSource": "admin",
        }
        with open("test_mongo_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(mongo_db_config, f)

        # correct config
        BaseDB.load_conf("test_mongo_config.json")
        # foreign field
        mongo_db_config_2 = copy.deepcopy(mongo_db_config)
        mongo_db_config_2["passworda"] = "mongononadminpassword"
        with open("test_mongo_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(mongo_db_config_2, f)
        self.assertRaises(pydantic.ValidationError, BaseDB.load_conf, "test_mongo_config.json")
        # missing field
        mongo_db_config_3 = copy.deepcopy(mongo_db_config)
        mongo_db_config_3.pop("password")
        with open("test_mongo_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(mongo_db_config_3, f)
        self.assertRaises(ValueError, BaseDB.load_conf, "test_mongo_config.json")
        # URI instead of other fields
        mongo_db_config = dict(
            provider="mongo",
            uri="mongodb://hololinked:mongononadminpassword@localhost:27017/hololinked?authSource=admin",
        )
        with open("test_mongo_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(mongo_db_config, f)
        # correct config
        BaseDB.load_conf("test_mongo_config.json")

        os.remove("test_mongo_config.json")

        # ----- SQLite config tests -----

        sqlite_db_config = {
            "provider": "sqlite",
            "file": "test_sqlite.db",
        }
        with open("test_sqlite_config.json", "w") as f:
            PythonBuiltinJSONSerializer.dump(sqlite_db_config, f)

        # correct config
        ThingDB(thing, config_file="test_sqlite_config.json")

        os.remove("test_sqlite_config.json")


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())
