import logging
import tempfile
import os
import copy
import pydantic
import pytest

from hololinked.core.properties import Number
from hololinked.storage.database import BaseDB, ThingDB
from hololinked.serializers import PythonBuiltinJSONSerializer
from hololinked.logger import setup_logging

try:
    from .things import TestThing
except ImportError:
    from things import TestThing

setup_logging(log_level=logging.ERROR)


@pytest.fixture(autouse=True)
def reset_class_properties():
    # Reset class properties to defaults before each test
    TestThing.simple_class_prop = 42
    TestThing.managed_class_prop = 0
    TestThing.deletable_class_prop = 100
    try:
        if not hasattr(TestThing, "not_a_class_prop"):
            from hololinked.core.properties import Number

            TestThing.not_a_class_prop = Number(default=43)
    except Exception:
        pass
    yield


def test_simple_class_property():
    # Test class-level access
    assert TestThing.simple_class_prop == 42
    TestThing.simple_class_prop = 100
    assert TestThing.simple_class_prop == 100

    # Test that instance-level access reflects class value
    instance1 = TestThing(id="test1")
    instance2 = TestThing(id="test2")
    assert instance1.simple_class_prop == 100
    assert instance2.simple_class_prop == 100

    # Test that instance-level changes affect class value
    instance1.simple_class_prop = 200
    assert TestThing.simple_class_prop == 200
    assert instance2.simple_class_prop == 200


def test_managed_class_property():
    # Test initial value
    assert TestThing.managed_class_prop == 0
    # Test valid value assignment
    TestThing.managed_class_prop = 50
    assert TestThing.managed_class_prop == 50
    # Test validation in setter
    with pytest.raises(ValueError):
        TestThing.managed_class_prop = -10
    # Verify value wasn't changed after failed assignment
    assert TestThing.managed_class_prop == 50
    # Test instance-level validation
    instance = TestThing(id="test3")
    with pytest.raises(ValueError):
        instance.managed_class_prop = -20
    # Test that instance-level access reflects class value
    assert instance.managed_class_prop == 50
    # Test that instance-level changes affects class value
    instance.managed_class_prop = 100
    assert TestThing.managed_class_prop == 100
    assert instance.managed_class_prop == 100


def test_readonly_class_property():
    # Test reading the value
    assert TestThing.readonly_class_prop == "read-only-value"

    # Test that setting raises an error at class level
    with pytest.raises(ValueError):
        TestThing.readonly_class_prop = "new-value"

    # Test that setting raises an error at instance level
    instance = TestThing(id="test4")
    with pytest.raises(ValueError):
        instance.readonly_class_prop = "new-value"

    # Verify value remains unchanged
    assert TestThing.readonly_class_prop == "read-only-value"
    assert instance.readonly_class_prop == "read-only-value"


def test_deletable_class_property():
    # Test initial value
    assert TestThing.deletable_class_prop == 100

    # Test setting new value
    TestThing.deletable_class_prop = 150
    assert TestThing.deletable_class_prop == 150

    # Test deletion
    instance = TestThing(id="test5")
    del TestThing.deletable_class_prop
    assert TestThing.deletable_class_prop == 100  # Should return to default
    assert instance.deletable_class_prop == 100

    # Test instance-level deletion
    instance.deletable_class_prop = 200
    assert TestThing.deletable_class_prop == 200
    del instance.deletable_class_prop
    assert TestThing.deletable_class_prop == 100  # Should return to default


def test_descriptor_access():
    # Test direct access through descriptor
    instance = TestThing(id="test6")
    assert isinstance(TestThing.not_a_class_prop, Number)
    assert instance.not_a_class_prop == 43
    instance.not_a_class_prop = 50
    assert instance.not_a_class_prop == 50

    del instance.not_a_class_prop
    # deleter deletes only an internal instance variable
    assert hasattr(TestThing, "not_a_class_prop")
    assert instance.not_a_class_prop == 43

    del TestThing.not_a_class_prop
    # descriptor itself is deleted
    assert not hasattr(TestThing, "not_a_class_prop")
    assert not hasattr(instance, "not_a_class_prop")
    with pytest.raises(AttributeError):
        _ = instance.not_a_class_prop


def _generate_db_ops_tests():
    def test_prekill(thing: TestThing):
        assert thing.db_commit_number_prop == 0
        thing.db_commit_number_prop = 100
        assert thing.db_commit_number_prop == 100
        assert thing.db_engine.get_property("db_commit_number_prop") == 100

        # test db persist property
        assert thing.db_persist_selector_prop == "a"
        thing.db_persist_selector_prop = "c"
        assert thing.db_persist_selector_prop == "c"
        assert thing.db_engine.get_property("db_persist_selector_prop") == "c"

        # test db init property
        assert thing.db_init_int_prop == TestThing.db_init_int_prop.default
        thing.db_init_int_prop = 50
        assert thing.db_init_int_prop == 50
        assert thing.db_engine.get_property("db_init_int_prop") != 50
        assert thing.db_engine.get_property("db_init_int_prop") == TestThing.db_init_int_prop.default
        del thing

    def test_postkill(thing: TestThing):
        # deleted thing and reload from database
        assert thing.db_init_int_prop == TestThing.db_init_int_prop.default
        assert thing.db_persist_selector_prop == "c"
        assert thing.db_commit_number_prop != 100
        assert thing.db_commit_number_prop == TestThing.db_commit_number_prop.default

    return test_prekill, test_postkill


def test_sqlalchemy_db_operations():
    thing_id = "test-db-operations"
    file_path = f"{thing_id}.db"
    try:
        os.remove(file_path)
    except (OSError, FileNotFoundError):
        pass
    assert not os.path.exists(file_path)

    test_prekill, test_postkill = _generate_db_ops_tests()

    thing = TestThing(id=thing_id, use_default_db=True)
    test_prekill(thing)

    thing = TestThing(id=thing_id, use_default_db=True)
    test_postkill(thing)


def test_json_db_operations():
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        filename = tf.name

    thing_id = "test-db-operations-json"
    test_prekill, test_postkill = _generate_db_ops_tests()

    thing = TestThing(
        id=thing_id,
        use_json_file=True,
        json_filename=filename,
    )
    test_prekill(thing)

    thing = TestThing(
        id=thing_id,
        use_json_file=True,
        json_filename=filename,
    )
    test_postkill(thing)

    os.remove(filename)


def test_db_config():
    thing = TestThing(id="test-sql-config")

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
    with pytest.raises(pydantic.ValidationError):
        ThingDB(thing, config_file="test_sql_config.json")
    # missing field
    sql_db_config_3 = copy.deepcopy(sql_db_config)
    sql_db_config_3.pop("password")
    with open("test_sql_config.json", "w") as f:
        PythonBuiltinJSONSerializer.dump(sql_db_config_3, f)
    with pytest.raises(ValueError):
        ThingDB(thing, config_file="test_sql_config.json")
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
    with pytest.raises(pydantic.ValidationError):
        BaseDB.load_conf("test_mongo_config.json")
    # missing field
    mongo_db_config_3 = copy.deepcopy(mongo_db_config)
    mongo_db_config_3.pop("password")
    with open("test_mongo_config.json", "w") as f:
        PythonBuiltinJSONSerializer.dump(mongo_db_config_3, f)
    with pytest.raises(ValueError):
        BaseDB.load_conf("test_mongo_config.json")
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
