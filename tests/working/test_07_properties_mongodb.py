import unittest
from hololinked.core.property import Property
from hololinked.core import Thing
from hololinked.storage.database import MongoThingDB
from pymongo import MongoClient

class TestMongoDBOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Clear MongoDB 'properties' collection before tests
        try:
            client = MongoClient("mongodb://localhost:27017")
            db = client["hololinked"]
            db["properties"].delete_many({})
        except Exception as e:
            print(f"Warning: Could not clear MongoDB test data: {e}")

    def test_mongo_string_property(self):
        class MongoTestThing(Thing):
            str_prop = Property(default="hello", db_persist=True)
        instance = MongoTestThing(id="mongo_str", use_mongo_db=True)
        instance.str_prop = "world"
        value_from_db = instance.db_engine.get_property("str_prop")
        self.assertEqual(value_from_db, "world")

    def test_mongo_float_property(self):
        class MongoTestThing(Thing):
            float_prop = Property(default=1.23, db_persist=True)
        instance = MongoTestThing(id="mongo_float", use_mongo_db=True)
        instance.float_prop = 4.56
        value_from_db = instance.db_engine.get_property("float_prop")
        self.assertAlmostEqual(value_from_db, 4.56)

    def test_mongo_bool_property(self):
        class MongoTestThing(Thing):
            bool_prop = Property(default=False, db_persist=True)
        instance = MongoTestThing(id="mongo_bool", use_mongo_db=True)
        instance.bool_prop = True
        value_from_db = instance.db_engine.get_property("bool_prop")
        self.assertTrue(value_from_db)

    def test_mongo_dict_property(self):
        class MongoTestThing(Thing):
            dict_prop = Property(default={"a": 1}, db_persist=True)
        instance = MongoTestThing(id="mongo_dict", use_mongo_db=True)
        instance.dict_prop = {"b": 2, "c": 3}
        value_from_db = instance.db_engine.get_property("dict_prop")
        self.assertEqual(value_from_db, {"b": 2, "c": 3})

    def test_mongo_list_property(self):
        class MongoTestThing(Thing):
            list_prop = Property(default=[1, 2], db_persist=True)
        instance = MongoTestThing(id="mongo_list", use_mongo_db=True)
        instance.list_prop = [3, 4, 5]
        value_from_db = instance.db_engine.get_property("list_prop")
        self.assertEqual(value_from_db, [3, 4, 5])

    def test_mongo_none_property(self):
        class MongoTestThing(Thing):
            none_prop = Property(default=None, db_persist=True, allow_None=True)
        instance = MongoTestThing(id="mongo_none", use_mongo_db=True)
        instance.none_prop = None
        value_from_db = instance.db_engine.get_property("none_prop")
        self.assertIsNone(value_from_db)

    def test_mongo_property_persistence(self):
        thing_id = "mongo_test_persistence_unique"
        prop_name = "test_prop_unique"
        client = MongoClient("mongodb://localhost:27017")
        db = client["hololinked"]
        db["properties"].delete_many({"id": thing_id, "name": prop_name})
        class MongoTestThing(Thing):
            test_prop_unique = Property(default=123, db_persist=True)
        instance = MongoTestThing(id=thing_id, use_mongo_db=True)
        instance.test_prop_unique = 456
        value_from_db = instance.db_engine.get_property(prop_name)
        self.assertEqual(value_from_db, 456)

if __name__ == "__main__":
    unittest.main()
