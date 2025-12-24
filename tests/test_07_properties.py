import copy
import json
import os

from dataclasses import dataclass
from typing import Callable

import pydantic
import pytest

from hololinked.core.properties import Number
from hololinked.storage.database import BaseDB, ThingDB
from hololinked.utils import uuid_hex


try:
    from .things import TestThing
except ImportError:
    from things import TestThing


@dataclass
class Defaults:
    SIMPLE_CLASS_PROP: int = 42
    MANAGED_CLASS_PROP: int = 0
    DELETABLE_CLASS_PROP: int = 100


@pytest.fixture(autouse=True)
def reset_class_properties():
    # Reset class properties to defaults before each test
    TestThing.simple_class_prop = Defaults.SIMPLE_CLASS_PROP
    TestThing.managed_class_prop = Defaults.MANAGED_CLASS_PROP
    TestThing.deletable_class_prop = Defaults.DELETABLE_CLASS_PROP

    yield


def test_01_simple_class_property():
    # Test class-level access
    assert TestThing.simple_class_prop == Defaults.SIMPLE_CLASS_PROP
    TestThing.simple_class_prop = 100
    assert TestThing.simple_class_prop == 100

    # Test that instance-level access reflects class value
    instance1 = TestThing(id=f"test-simple-class-prop-{uuid_hex()}")
    instance2 = TestThing(id=f"test-simple-class-prop-{uuid_hex()}")
    assert instance1.simple_class_prop == 100
    assert instance2.simple_class_prop == 100

    # Test that instance-level changes affect class value
    instance1.simple_class_prop = 200
    assert TestThing.simple_class_prop == 200
    assert instance2.simple_class_prop == 200


def test_02_managed_class_property():
    # Test initial value
    assert TestThing.managed_class_prop == Defaults.MANAGED_CLASS_PROP
    # Test valid value assignment
    TestThing.managed_class_prop = 50
    assert TestThing.managed_class_prop == 50
    # Test validation in setter
    with pytest.raises(ValueError):
        TestThing.managed_class_prop = -10
    # Verify value wasn't changed after failed assignment
    assert TestThing.managed_class_prop == 50
    # Test instance-level validation
    instance = TestThing(id=f"test-managed-class-prop-{uuid_hex()}")
    with pytest.raises(ValueError):
        instance.managed_class_prop = -20
    # Test that instance-level access reflects class value
    assert instance.managed_class_prop == 50
    # Test that instance-level changes affects class value
    instance.managed_class_prop = 100
    assert TestThing.managed_class_prop == 100
    assert instance.managed_class_prop == 100


def test_03_readonly_class_property():
    # Test reading the value
    assert TestThing.readonly_class_prop == "read-only-value"

    # Test that setting raises an error at class level
    with pytest.raises(ValueError):
        TestThing.readonly_class_prop = "new-value"

    # Test that setting raises an error at instance level
    instance = TestThing(id=f"test-readonly-class-prop-{uuid_hex()}")
    with pytest.raises(ValueError):
        instance.readonly_class_prop = "new-value"

    # Verify value remains unchanged
    assert TestThing.readonly_class_prop == "read-only-value"
    assert instance.readonly_class_prop == "read-only-value"


def test_04_deletable_class_property():
    # Test initial value
    assert TestThing.deletable_class_prop == Defaults.DELETABLE_CLASS_PROP

    # Test setting new value
    TestThing.deletable_class_prop = 150
    assert TestThing.deletable_class_prop == 150

    # Test deletion
    instance = TestThing(id=f"test-deletable-class-prop-{uuid_hex()}")
    del TestThing.deletable_class_prop
    assert TestThing.deletable_class_prop == Defaults.DELETABLE_CLASS_PROP  # Should return to default
    assert instance.deletable_class_prop == Defaults.DELETABLE_CLASS_PROP

    # Test instance-level deletion
    instance.deletable_class_prop = 200
    assert TestThing.deletable_class_prop == 200
    del instance.deletable_class_prop
    assert TestThing.deletable_class_prop == Defaults.DELETABLE_CLASS_PROP  # Should return to default


def test_05_descriptor_access():
    # Test direct access through descriptor
    instance = TestThing(id=f"test-descriptor-access-{uuid_hex()}")
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


@pytest.fixture(scope="module")
def db_ops_tests() -> tuple[Callable, Callable]:
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


def test_06_sqlalchemy_db_operations(db_ops_tests: tuple[Callable, Callable]):
    thing_id = f"test-db-operations-sqlalchemy-{uuid_hex()}"

    test_prekill, test_postkill = db_ops_tests

    thing = TestThing(id=thing_id, use_default_db=True)
    test_prekill(thing)

    thing = TestThing(id=thing_id, use_default_db=True)
    test_postkill(thing)


def test_07_json_db_operations(db_ops_tests: tuple[Callable, Callable]):
    filename = f"filename-name-{uuid_hex()}.json"

    thing_id = f"test-db-operations-json-{uuid_hex()}"
    test_prekill, test_postkill = db_ops_tests

    thing = TestThing(id=thing_id, use_json_file=True, json_filename=filename)
    test_prekill(thing)

    thing = TestThing(id=thing_id, use_json_file=True, json_filename=filename)
    test_postkill(thing)


def test_08_db_config():
    thing = TestThing(id=f"test-sql-config-{uuid_hex()}")

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
        json.dump(sql_db_config, f)

    # correct config
    ThingDB(thing, config_file="test_sql_config.json")
    # foreign field
    sql_db_config_2 = copy.deepcopy(sql_db_config)
    sql_db_config_2["passworda"] = "postgresnonadminpassword"
    with open("test_sql_config.json", "w") as f:
        json.dump(sql_db_config_2, f)
    with pytest.raises(pydantic.ValidationError):
        ThingDB(thing, config_file="test_sql_config.json")
    # missing field
    sql_db_config_3 = copy.deepcopy(sql_db_config)
    sql_db_config_3.pop("password")
    with open("test_sql_config.json", "w") as f:
        json.dump(sql_db_config_3, f)
    with pytest.raises(ValueError):
        ThingDB(thing, config_file="test_sql_config.json")
    # URI instead of other fields
    sql_db_config = dict(
        provider="postgresql",
        uri="postgresql://hololinked:postgresnonadminpassword@localhost:5432/hololinked",
    )
    with open("test_sql_config.json", "w") as f:
        json.dump(sql_db_config, f)
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
        json.dump(mongo_db_config, f)

    # correct config
    BaseDB.load_conf("test_mongo_config.json")
    # foreign field
    mongo_db_config_2 = copy.deepcopy(mongo_db_config)
    mongo_db_config_2["passworda"] = "mongononadminpassword"
    with open("test_mongo_config.json", "w") as f:
        json.dump(mongo_db_config_2, f)
    with pytest.raises(pydantic.ValidationError):
        BaseDB.load_conf("test_mongo_config.json")
    # missing field
    mongo_db_config_3 = copy.deepcopy(mongo_db_config)
    mongo_db_config_3.pop("password")
    with open("test_mongo_config.json", "w") as f:
        json.dump(mongo_db_config_3, f)
    with pytest.raises(ValueError):
        BaseDB.load_conf("test_mongo_config.json")
    # URI instead of other fields
    mongo_db_config = dict(
        provider="mongo",
        uri="mongodb://hololinked:mongononadminpassword@localhost:27017/hololinked?authSource=admin",
    )
    with open("test_mongo_config.json", "w") as f:
        json.dump(mongo_db_config, f)
    # correct config
    BaseDB.load_conf("test_mongo_config.json")

    os.remove("test_mongo_config.json")

    # ----- SQLite config tests -----

    sqlite_db_config = {
        "provider": "sqlite",
        "file": "test_sqlite.db",
    }
    with open("test_sqlite_config.json", "w") as f:
        json.dump(sqlite_db_config, f)

    # correct config
    ThingDB(thing, config_file="test_sqlite_config.json")

    os.remove("test_sqlite_config.json")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
