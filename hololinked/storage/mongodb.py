"""Implementation of MongoDB-based database engine."""

from __future__ import annotations

import base64

from typing import TYPE_CHECKING, Any

from pymongo import MongoClient
from pymongo import errors as mongo_errors

from hololinked import Serializers
from hololinked.storage.bases import BaseDB


if TYPE_CHECKING:
    from hololinked.core.property import Property
    from hololinked.core.thing import Thing


class MongoDB(BaseDB):
    """
    Provides persistence for Thing properties using MongoDB.

    Properties are stored in a 'properties' collection, with fields:

    - id: Thing instance identifier
    - name: property name
    - serialized_value: serialized property value
    """

    def __init__(self, thing: Thing, config_file: str) -> None:
        """
        Initialize MongoDB for a Thing instance.

        Connects to MongoDB and sets up collections.

        Parameters
        ----------
        thing: Thing
            The `Thing` instance which uses this database engine for configuration storage.
        config_file: str
            Path to the MongoDB configuration file.
        """
        super().__init__(thing=thing, config_file=config_file)
        self.client = MongoClient(self.config.URL)
        self.db = self.client[self.config.database]
        self.properties = self.db["properties"]
        self.things = self.db["things"]

    def fetch_own_info(self):
        """
        Fetch `Thing` instance's own information (some useful metadata which helps the `Thing` run).

        Highly unused and irrelevant currently.

        Returns
        -------
        dict[str, Any] | None
            Metadata document for the Thing instance, or None if not found.
        """
        doc = self.things.find_one({"id": self.thing.id})
        return doc

    def get_property(self, property: str | Property, deserialized: bool = True) -> Any:
        """
        Fetch a single property value from the database.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        deserialized: bool, default True
            deserialize the property if True

        Returns
        -------
        Any
            property value

        Raises
        ------
        PyMongoError
            if the property is not found in database
        """
        name = property if isinstance(property, str) else property.name
        doc = self.properties.find_one({"id": self.thing.id, "name": name})
        if not doc:
            raise mongo_errors.PyMongoError(f"property {name} not found in database")
        if not deserialized:
            return doc
        serializer = Serializers.for_object(self.thing.id, self.thing.__class__.__name__, name)
        return serializer.loads(base64.b64decode(doc["serialized_value"]))

    def set_property(self, property: str | Property, value: Any) -> None:
        """
        Change the value of an already existing property in the database.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        value: Any
            value of the property
        """
        name = property if isinstance(property, str) else property.name
        serializer = Serializers.for_object(self.thing.id, self.thing.__class__.__name__, name)
        serialized_value = base64.b64encode(serializer.dumps(value)).decode("utf-8")
        self.properties.update_one(
            {"id": self.thing.id, "name": name}, {"$set": {"serialized_value": serialized_value}}, upsert=True
        )

    def get_properties(self, properties: dict[str | Property, Any], deserialized: bool = True) -> dict[str, Any]:
        """
        Get multiple properties at once from the database.

        Parameters
        ----------
        properties: List[str | Property]
            string names or the descriptor of the properties as a list
        deserialized: bool, default True
            deserialize the properties if True

        Returns
        -------
        dict[str, Any]
            property names and values as items
        """
        names = [obj if isinstance(obj, str) else obj.name for obj in properties.keys()]
        cursor = self.properties.find({"id": self.thing.id, "name": {"$in": names}})
        result = {}
        for doc in cursor:
            serializer = Serializers.for_object(self.thing.id, self.thing.__class__.__name__, doc["name"])
            result[doc["name"]] = (
                doc["serialized_value"]
                if not deserialized
                else serializer.loads(base64.b64decode(doc["serialized_value"]))
            )
        return result

    def set_properties(self, properties: dict[str | Property, Any]) -> None:
        """
        Change the values of already existing properties at once in the database.

        Parameters
        ----------
        properties: Dict[str | Property, Any]
            string names or the descriptor of the property and any value as dictionary pairs
        """
        for obj, value in properties.items():
            name = obj if isinstance(obj, str) else obj.name
            serializer = Serializers.for_object(self.thing.id, self.thing.__class__.__name__, name)
            serialized_value = base64.b64encode(serializer.dumps(value)).decode("utf-8")
            self.properties.update_one(
                {"id": self.thing.id, "name": name},
                {"$set": {"serialized_value": serialized_value}},
                upsert=True,
            )

    def get_all_properties(self, deserialized: bool = True) -> dict[str, Any]:
        """
        Get all properties of the `Thing` instance stored in the database.

        Parameters
        ----------
        deserialized: bool, default True
            deserialize the properties if True

        Returns
        -------
        dict[str, Any]
            property names and values as items
        """
        cursor = self.properties.find({"id": self.thing.id})
        result = {}
        for doc in cursor:
            serializer = Serializers.for_object(self.thing.id, self.thing.__class__.__name__, doc["name"])
            result[doc["name"]] = (
                doc["serialized_value"]
                if not deserialized
                else serializer.loads(base64.b64decode(doc["serialized_value"]))
            )
        return result

    def create_missing_properties(
        self,
        properties: dict[str, Property],
        get_missing_property_names: bool = False,
    ) -> Any:
        """
        Create any and all missing properties of `Thing` instance in database.

        Parameters
        ----------
        properties: Dict[str, Property]
            descriptors of the properties
        get_missing_property_names: bool, default False
            whether to return the list of missing property names

        Returns
        -------
        List[str]
            list of missing properties if get_missing_property_names is True
        """
        missing_props = []
        existing_props = self.get_all_properties()
        for name, new_prop in properties.items():
            if name not in existing_props:
                serializer = Serializers.for_object(self.thing.id, self.thing.__class__.__name__, new_prop.name)
                serialized_value = base64.b64encode(serializer.dumps(getattr(self.thing, new_prop.name))).decode(
                    "utf-8"
                )
                self.properties.insert_one(
                    {"id": self.thing.id, "name": new_prop.name, "serialized_value": serialized_value}
                )
                missing_props.append(name)
        if get_missing_property_names:
            return missing_props


__all__ = [
    MongoDB.__name__,
]
