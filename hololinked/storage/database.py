import threading
import typing
import base64
from sqlalchemy import create_engine, select, inspect as inspect_database
from datetime import datetime
from sqlalchemy import create_engine, select, inspect as inspect_database, String, JSON, LargeBinary, Integer
from sqlalchemy.ext import asyncio as asyncio_ext
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column, DeclarativeBase, MappedAsDataclass
from sqlite3 import DatabaseError
from pymongo import MongoClient, errors as mongo_errors
from dataclasses import dataclass
from dataclasses import dataclass, asdict

from ..param import Parameterized
from ..core.property import Property
from ..constants import JSONSerializable
from ..serializers.serializers import PythonBuiltinJSONSerializer as JSONSerializer, BaseSerializer, Serializers
from ..core.property import Property
from .config_models import MongoDBConfig, SQLDBConfig, SQLiteConfig


class ThingTableBase(DeclarativeBase):
    """SQLAlchemy base table for all thing related tables"""

    pass


class SerializedProperty(MappedAsDataclass, ThingTableBase):
    """
    Property value is serialized before storing in database, therefore providing unified version for
    SQLite and other relational tables
    """

    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    serialized_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    thing_id: Mapped[str] = mapped_column(String)
    thing_class: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String, nullable=False, default="application/json")


class ThingInformation(MappedAsDataclass, ThingTableBase):
    """Stores information about the Thing instance itself, useful metadata which may be later populated in a GUI"""

    __tablename__ = "things"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thing_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    thing_class: Mapped[str] = mapped_column(String, nullable=False)
    script: Mapped[str] = mapped_column(String)
    init_kwargs: Mapped[JSONSerializable] = mapped_column(JSON)
    server_id: Mapped[str] = mapped_column(String)

    def json(self):
        return asdict(self)


@dataclass
class DeserializedProperty:  # not part of database
    """Property with deserialized value after fetching from database"""

    thing_id: str
    name: str
    value: typing.Any
    created_at: str
    updated_at: str


class BaseDB:
    """Implements configuration file reader for all irrespective sync or async DB operation"""

    def __init__(self, instance: Parameterized, config_file: typing.Union[str, None] = None) -> None:
        self.thing_instance = instance
        self.conf = BaseDB.load_conf(config_file, default_file_path=f"{instance.id}.db")
        self.URL = self.conf.URL
        self._batch_call_context = {}

    @classmethod
    def load_conf(
        cls,
        config_file: str,
        default_file_path: str = "",
    ) -> typing.Union[SQLDBConfig, SQLiteConfig, MongoDBConfig]:
        """
        load configuration file using JSON serializer
        """
        if not config_file:
            return SQLiteConfig(file=default_file_path)
        elif config_file.endswith(".json"):
            file = open(config_file, "r")
            conf = JSONSerializer.load(file)
            if conf.get("provider", None) in ["postgresql", "mysql"]:
                return SQLDBConfig.model_validate(conf, strict=True, from_attributes=True)
            elif conf.get("provider", None) == "sqlite":
                return SQLiteConfig.model_validate(conf, strict=True, from_attributes=True)
            elif conf.get("provider", None) == "mongo":
                return MongoDBConfig.model_validate(conf, strict=True, from_attributes=True)
            raise NotImplementedError("only postgresql, mysql, sqlite and mongo are supported")
        raise ValueError("config files of extension {} expected, given file name {}".format(["json"], config_file))

    @property
    def in_batch_call_context(self):
        return threading.get_ident() in self._batch_call_context


class BaseAsyncDB(BaseDB):
    """
    Base class for an async database engine, implements configuration file reader,
    sqlalchemy engine & session creation. Set `async_db_engine` boolean flag to True in `Thing` class
    to use this engine. Database operations are then scheduled in the event loop instead of blocking the current thread.
    Scheduling happens after properties are set/written.

    Parameters
    ----------
    database: str
        The database to open in the database server specified in config_file (see below)
    serializer: BaseSerializer
        The serializer to use for serializing and deserializing data (for example
        property serializing before writing to database). Will be the same as zmq_serializer supplied to `Thing`.
    config_file: str
        absolute path to database server configuration file
    """

    def __init__(
        self,
        instance: Parameterized,
        serializer: typing.Optional[BaseSerializer] = None,
        config_file: typing.Union[str, None] = None,
    ) -> None:
        super().__init__(instance=instance, serializer=serializer, config_file=config_file)
        self.engine = asyncio_ext.create_async_engine(self.URL)
        self.async_session = sessionmaker(self.engine, expire_on_commit=True, class_=asyncio_ext.AsyncSession)
        if self.conf.provider == "sqlite":
            ThingTableBase.metadata.create_all(self.engine)


class BaseSyncDB(BaseDB):
    """
    Base class for an synchronous (blocking) database engine, implements configuration file reader, sqlalchemy engine
    & session creation. Default DB engine for `Thing` & called immediately after properties are set/written.

    Parameters
    ----------
    database: str
        The database to open in the database server specified in config_file (see below)
    serializer: BaseSerializer
        The serializer to use for serializing and deserializing data (for example
        property serializing into database for storage). Will be the same as
        zmq_serializer supplied to `Thing`.
    config_file: str
        absolute path to database server configuration file
    """

    def __init__(self, instance: Parameterized, config_file: typing.Union[str, None] = None) -> None:
        super().__init__(instance=instance, config_file=config_file)
        self.engine = create_engine(self.URL)
        self.sync_session = sessionmaker(self.engine, expire_on_commit=True)
        if self.conf.provider == "sqlite":
            ThingTableBase.metadata.create_all(self.engine)


class ThingDB(BaseSyncDB):
    """
    Database engine composed within `Thing`, carries out database operations like storing object information, properties
    etc.

    Parameters
    ----------
    id: str
        `id` of the `Thing`
    config_file: str
        configuration file of the database server
    """

    def fetch_own_info(self):  # -> ThingInformation:
        """
        fetch `Thing` instance's own information (some useful metadata which helps the `Thing` run).

        Returns
        -------
        `ThingInformation`
        """
        if not inspect_database(self.engine).has_table("things"):
            return
        with self.sync_session() as session:
            stmt = select(ThingInformation).filter_by(
                thing_id=self.thing_instance.id, thing_class=self.thing_instance.__class__.__name__
            )
            data = session.execute(stmt)
            data = data.scalars().all()
            if len(data) == 0:
                return None
            elif len(data) == 1:
                return data[0]
            else:
                raise DatabaseError(
                    "Multiple things with same instance name found, either cleanup database/detach/make new"
                )

    def get_property(self, property: typing.Union[str, Property], deserialized: bool = True) -> typing.Any:
        """
        fetch a single property.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        deserialized: bool, default True
            deserialize the property if True

        Returns
        -------
        value: Any
            property value
        """
        with self.sync_session() as session:
            name = property if isinstance(property, str) else property.name
            stmt = select(SerializedProperty).filter_by(
                thing_id=self.thing_instance.id,
                thing_class=self.thing_instance.__class__.__name__,
                name=name,
            )
            data = session.execute(stmt)
            prop = data.scalars().all()  # type: typing.Sequence[SerializedProperty]
            if len(prop) == 0:
                raise DatabaseError(f"property {name} not found in database")
            elif len(prop) > 1:
                raise DatabaseError("multiple properties with same name found")  # Impossible actually
            if not deserialized:
                return prop[0]
            serializer = Serializers.content_types.get(prop[0].content_type, None) or Serializers.for_object(
                self.thing_instance.id, self.thing_instance.__class__.__name__, name
            )
            return serializer.loads(prop[0].serialized_value)

    def set_property(self, property: typing.Union[str, Property], value: typing.Any) -> None:
        """
        change the value of an already existing property.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        value: Any
            value of the property
        """
        if self.in_batch_call_context:
            self._batch_call_context[threading.get_ident()][property.name] = value
            return
        with self.sync_session() as session:
            name = property if isinstance(property, str) else property.name
            stmt = select(SerializedProperty).filter_by(
                thing_id=self.thing_instance.id,
                thing_class=self.thing_instance.__class__.__name__,
                name=name,
            )
            data = session.execute(stmt)
            prop = data.scalars().all()
            if len(prop) > 1:
                raise DatabaseError("multiple properties with same name found")  # Impossible actually
            if len(prop) == 1:
                prop = prop[0]
                serializer = Serializers.content_types.get(prop.content_type, None) or Serializers.for_object(
                    self.thing_instance.id, self.thing_instance.__class__.__name__, name
                )
                prop.serialized_value = serializer.dumps(value)
                prop.updated_at = datetime.now().isoformat()
                prop.content_type = serializer.content_type
            else:
                serializer = Serializers.for_object(
                    self.thing_instance.id, self.thing_instance.__class__.__name__, name
                )
                now = datetime.now().isoformat()
                prop = SerializedProperty(
                    id=None,
                    name=name,
                    serialized_value=serializer.dumps(value),
                    thing_id=self.thing_instance.id,
                    thing_class=self.thing_instance.__class__.__name__,
                    created_at=now,
                    updated_at=now,
                    content_type=serializer.content_type,
                )
                session.add(prop)
            session.commit()

    def get_properties(
        self, properties: typing.Dict[typing.Union[str, Property], typing.Any], deserialized: bool = True
    ) -> typing.Dict[str, typing.Any]:
        """
        get multiple properties at once.

        Parameters
        ----------
        properties: List[str | Property]
            string names or the descriptor of the properties as a list

        Returns
        -------
        value: Dict[str, Any]
            property names and values as items
        """
        with self.sync_session() as session:
            names = []
            for obj in properties.keys():
                names.append(obj if isinstance(obj, str) else obj.name)
            stmt = (
                select(SerializedProperty)
                .filter_by(thing_id=self.thing_instance.id, thing_class=self.thing_instance.__class__.__name__)
                .filter(SerializedProperty.name.in_(names))
            )
            data = session.execute(stmt)
            unserialized_props = data.scalars().all()
            props = dict()
            for prop in unserialized_props:
                serializer = Serializers.content_types.get(prop.content_type, None) or Serializers.for_object(
                    self.thing_instance.id, self.thing_instance.__class__.__name__, prop.name
                )
                props[prop.name] = (
                    prop.serialized_value if not deserialized else serializer.loads(prop.serialized_value)
                )
            return props

    def set_properties(self, properties: typing.Dict[typing.Union[str, Property], typing.Any]) -> None:
        """
        change the values of already existing few properties at once

        Parameters
        ----------
        properties: Dict[str | Property, Any]
            string names or the descriptor of the property and any value as dictionary pairs
        """
        if self.in_batch_call_context:
            for obj, value in properties.items():
                name = obj if isinstance(obj, str) else obj.name
                self._batch_call_context[threading.get_ident()][name] = value
            return
        with self.sync_session() as session:
            names = []
            for obj in properties.keys():
                names.append(obj if isinstance(obj, str) else obj.name)
            stmt = (
                select(SerializedProperty)
                .filter_by(thing_id=self.thing_instance.id, thing_class=self.thing_instance.__class__.__name__)
                .filter(SerializedProperty.name.in_(names))
            )
            data = session.execute(stmt)
            db_props = data.scalars().all()
            for obj, value in properties.items():
                name = obj if isinstance(obj, str) else obj.name
                db_prop = list(filter(lambda db_prop: db_prop.name == name, db_props))  # type: typing.List[SerializedProperty]
                if len(db_prop) > 1:
                    raise DatabaseError("multiple properties with same name found")  # Impossible actually
                if len(db_prop) == 1:
                    db_prop = db_prop[0]  # type: SerializedProperty
                    serializer = Serializers.content_types.get(db_prop.content_type, None) or Serializers.for_object(
                        self.thing_instance.id, self.thing_instance.__class__.__name__, name
                    )
                    db_prop.serialized_value = serializer.dumps(value)
                    db_prop.updated_at = datetime.now().isoformat()
                    db_prop.content_type = serializer.content_type
                else:
                    serializer = Serializers.for_object(
                        self.thing_instance.id, self.thing_instance.__class__.__name__, name
                    )
                    now = datetime.now().isoformat()
                    prop = SerializedProperty(
                        id=None,
                        name=name,
                        serialized_value=serializer.dumps(value),
                        thing_id=self.thing_instance.id,
                        thing_class=self.thing_instance.__class__.__name__,
                        created_at=now,
                        updated_at=now,
                        content_type=serializer.content_type,
                    )
                    session.add(prop)
            session.commit()

    def get_all_properties(self, deserialized: bool = True) -> typing.Dict[str, typing.Any]:
        """
        read all properties of the `Thing` instance.

        Parameters
        ----------
        deserialized: bool, default True
            deserilize the properties if True
        """
        with self.sync_session() as session:
            stmt = select(SerializedProperty).filter_by(
                thing_id=self.thing_instance.id, thing_class=self.thing_instance.__class__.__name__
            )
            data = session.execute(stmt)
            existing_props = data.scalars().all()  # type: typing.Sequence[SerializedProperty]
            if not deserialized:
                return existing_props
            props = dict()
            for prop in existing_props:
                serializer = Serializers.content_types.get(prop.content_type, None) or Serializers.for_object(
                    self.thing_instance.id, self.thing_instance.__class__.__name__, prop.name
                )
                props[prop.name] = serializer.loads(prop.serialized_value)
            return props

    def create_missing_properties(
        self, properties: typing.Dict[str, Property], get_missing_property_names: bool = False
    ) -> None:
        """
        create any and all missing properties of `Thing` instance in database.

        Parameters
        ----------
        properties: Dict[str, Property]
            descriptors of the properties

        Returns
        -------
        List[str]
            list of missing properties if get_missing_property_names is True
        """
        missing_props = []
        with self.sync_session() as session:
            existing_props = self.get_all_properties()
            for prop in properties.values():
                if prop.name not in existing_props:
                    serializer = Serializers.for_object(
                        self.thing_instance.id, self.thing_instance.__class__.__name__, prop.name
                    )
                    now = datetime.now().isoformat()
                    prop = SerializedProperty(
                        id=None,
                        name=prop.name,
                        serialized_value=serializer.dumps(getattr(self.thing_instance, prop.name)),
                        thing_id=self.thing_instance.id,
                        thing_class=self.thing_instance.__class__.__name__,
                        created_at=now,
                        updated_at=now,
                        content_type=serializer.content_type,
                    )
                    session.add(prop)
                    missing_props.append(prop.name)
            session.commit()
        if get_missing_property_names:
            return missing_props

    def create_db_init_properties(
        self, thing_id: str = None, thing_class: str = None, **properties: typing.Any
    ) -> None:
        """
        Create properties that are initialized from database for a thing instance.
        Invoke this method once before running the thing instance to store its initial value in database.

        Parameters
        ----------
        thing_id: str
            ID of the thing instance to which these properties belong
        thing_class: str
            Class name of the thing instance to which these properties belong
        properties: Dict[str, Any]
            property names and their initial values as dictionary pairs
        """
        with self.sync_session() as session:
            for name, value in properties.items():
                serializer = Serializers.for_object(thing_id, thing_class, name)
                now = datetime.now().isoformat()
                prop = SerializedProperty(
                    id=None,
                    name=name,
                    serialized_value=serializer.dumps(value),
                    thing_id=thing_id,
                    thing_class=thing_class,
                    created_at=now,
                    updated_at=now,
                    content_type=serializer.content_type,
                )
                session.add(prop)
            session.commit()


class batch_db_commit:
    """
    Context manager to write multiple properties to database at once. Useful for sequential sets/writes of multiple properties
    which has db_commit or db_persist set to True, but only write their values to database at once.
    """

    def __init__(self, db_engine: ThingDB) -> None:
        self.db_engine = db_engine

    def __enter__(self) -> None:
        self.db_engine._context[threading.get_ident()] = dict()

    def __exit__(self, exc_type, exc_value, exc_tb) -> None:
        data = self.db_engine._context.pop(threading.get_ident(), dict())  # typing.Dict[str, typing.Any]
        if exc_type is None:
            self.db_engine.set_properties(data)
            return
        for name, value in data.items():
            try:
                self.db_engine.set_property(name, value)
            except Exception as ex:
                self.db_engine.thing_instance.logger.error(
                    f"failed to set property {name} to value {value} during batch commit due to exception {ex}"
                )


class MongoThingDB:
    """
    MongoDB-backed database engine for Thing properties and info.

    This class provides persistence for Thing properties using MongoDB.
    Properties are stored in the 'properties' collection, with fields:
    - id: Thing instance identifier
    - name: property name
    - serialized_value: serialized property value

    Methods mirror the interface of ThingDB for compatibility.
    """

    def __init__(self, instance: Parameterized, config_file: typing.Union[str, None] = None) -> None:
        """
        Initialize MongoThingDB for a Thing instance.
        Connects to MongoDB and sets up collections.
        """
        self.thing_instance = instance
        self.id = instance.id
        self.config = self.load_conf(config_file)
        self.client = MongoClient(self.config.get("mongo_uri", "mongodb://localhost:27017"))
        self.db = self.client[self.config.get("database", "hololinked")]
        self.properties = self.db["properties"]
        self.things = self.db["things"]

    @classmethod
    def load_conf(cls, config_file: str) -> typing.Dict[str, typing.Any]:
        """
        Load configuration from JSON file if provided.
        """
        if not config_file:
            return {}
        elif config_file.endswith(".json"):
            with open(config_file, "r") as file:
                return JSONSerializer.load(file)
        else:
            raise ValueError(f"config files of extension - ['json'] expected, given file name {config_file}")

    def fetch_own_info(self):
        """
        Fetch Thing instance metadata from the 'things' collection.
        """
        doc = self.things.find_one({"id": self.id})
        return doc

    def get_property(self, property: typing.Union[str, Property], deserialized: bool = True) -> typing.Any:
        """
        Get a property value from MongoDB for this Thing.
        If deserialized=True, returns the Python value.
        """
        name = property if isinstance(property, str) else property.name
        doc = self.properties.find_one({"id": self.id, "name": name})
        if not doc:
            raise mongo_errors.PyMongoError(f"property {name} not found in database")
        if not deserialized:
            return doc
        serializer = Serializers.for_object(self.id, self.thing_instance.__class__.__name__, name)
        return serializer.loads(base64.b64decode(doc["serialized_value"]))

    def set_property(self, property: typing.Union[str, Property], value: typing.Any) -> None:
        """
        Set a property value in MongoDB for this Thing.
        Value is serialized before storage.
        """
        name = property if isinstance(property, str) else property.name
        serializer = Serializers.for_object(self.id, self.thing_instance.__class__.__name__, name)
        serialized_value = base64.b64encode(serializer.dumps(value)).decode("utf-8")
        self.properties.update_one(
            {"id": self.id, "name": name}, {"$set": {"serialized_value": serialized_value}}, upsert=True
        )

    def get_properties(
        self, properties: typing.Dict[typing.Union[str, Property], typing.Any], deserialized: bool = True
    ) -> typing.Dict[str, typing.Any]:
        """
        Get multiple property values from MongoDB for this Thing.
        Returns a dict of property names to values.
        """
        names = [obj if isinstance(obj, str) else obj.name for obj in properties.keys()]
        cursor = self.properties.find({"id": self.id, "name": {"$in": names}})
        result = {}
        for doc in cursor:
            serializer = Serializers.for_object(self.id, self.thing_instance.__class__.__name__, doc["name"])
            result[doc["name"]] = (
                doc["serialized_value"]
                if not deserialized
                else serializer.loads(base64.b64decode(doc["serialized_value"]))
            )
        return result

    def set_properties(self, properties: typing.Dict[typing.Union[str, Property], typing.Any]) -> None:
        """
        Set multiple property values in MongoDB for this Thing.
        """
        for obj, value in properties.items():
            name = obj if isinstance(obj, str) else obj.name
            serializer = Serializers.for_object(self.id, self.thing_instance.__class__.__name__, name)
            serialized_value = base64.b64encode(serializer.dumps(value)).decode("utf-8")
            self.properties.update_one(
                {"id": self.id, "name": name}, {"$set": {"serialized_value": serialized_value}}, upsert=True
            )

    def get_all_properties(self, deserialized: bool = True) -> typing.Dict[str, typing.Any]:
        cursor = self.properties.find({"id": self.id})
        result = {}
        for doc in cursor:
            serializer = Serializers.for_object(self.id, self.thing_instance.__class__.__name__, doc["name"])
            result[doc["name"]] = (
                doc["serialized_value"]
                if not deserialized
                else serializer.loads(base64.b64decode(doc["serialized_value"]))
            )
        return result

    def create_missing_properties(
        self, properties: typing.Dict[str, Property], get_missing_property_names: bool = False
    ) -> typing.Any:
        missing_props = []
        existing_props = self.get_all_properties()
        for name, new_prop in properties.items():
            if name not in existing_props:
                serializer = Serializers.for_object(self.id, self.thing_instance.__class__.__name__, new_prop.name)
                serialized_value = base64.b64encode(
                    serializer.dumps(getattr(self.thing_instance, new_prop.name))
                ).decode("utf-8")
                self.properties.insert_one({"id": self.id, "name": new_prop.name, "serialized_value": serialized_value})
                missing_props.append(name)
        if get_missing_property_names:
            return missing_props


__all__ = [BaseAsyncDB.__name__, BaseSyncDB.__name__, ThingDB.__name__, batch_db_commit.__name__]
