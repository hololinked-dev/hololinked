"""Implementation of SQLAlchemy-based database engines."""

from __future__ import annotations

import threading

from datetime import datetime
from sqlite3 import DatabaseError
from typing import TYPE_CHECKING, Any, Sequence

from sqlalchemy import create_engine, select
from sqlalchemy import inspect as inspect_database
from sqlalchemy.orm import sessionmaker

from hololinked import Serializers
from hololinked.storage.bases import BaseDB
from hololinked.storage.config import SQLDBConfig, SQLiteConfig
from hololinked.storage.models import (
    SerializedProperty,
    ThingInformation,
    ThingTableBase,
)


if TYPE_CHECKING:
    from hololinked.core.property import Property
    from hololinked.core.thing import Thing

"""
class BaseAsyncDB(DBEngineMixin, BaseConfigurationRepository):
    Base class for an async database engine, creates sqlalchemy engine & session.

    This class is not fully implemented yet.

    Set `async_db_engine` boolean flag to True in `Thing` class to use this engine.
    Database operations are then scheduled in the event loop instead of blocking the current thread.
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

    def __init__(
        self,
        thing,
        serializer: BaseSerializer | None = None,
        config_file: str | None = None,
    ) -> None:
        super().__init__(thing=thing, serializer=serializer, config_file=config_file)
        self.engine = asyncio_ext.create_async_engine(self.config.URL)
        self.async_session = sessionmaker(self.engine, expire_on_commit=True, class_=asyncio_ext.AsyncSession)
        if self.config.provider == "sqlite":
            ThingTableBase.metadata.create_all(self.engine)
"""


class BaseSyncDB(BaseDB):
    """
    Base class for a synchronous (blocking) database engine, implements sqlalchemy engine & session creation.

    Default DB engine for `Thing` & called immediately after properties are set/written.
    """

    def __init__(self, thing: Thing, config_file: str | None = None) -> None:
        """
        Initialize BaseSyncDB for a Thing instance.

        Parameters
        ----------
        thing: Thing
            The `Thing` instance which uses this database engine for configuration storage.
        config_file: str, optional
            Path to the database configuration file. `sqlite` backend with default settings will be used if not provided.

        Raises
        ------
        ValueError
            If the loaded configuration is not a valid config for SQLAlchemy-based database engines
            (but a valid config of another type).
        """
        super().__init__(thing=thing, config_file=config_file)
        if not isinstance(self.config, (SQLDBConfig, SQLiteConfig)):
            raise ValueError(f"You might have provided invalid SQLAlchemy config. Loaded config: {self.config}")
        self.engine = create_engine(self.config.URL)
        self.sync_session = sessionmaker(self.engine, expire_on_commit=True)
        if self.config.provider == "sqlite":
            ThingTableBase.metadata.create_all(self.engine)


class SQLAlchemyDB(BaseSyncDB):
    """SQLAlchemy-based database engine composed within `Thing`."""

    def fetch_own_info(self):  # -> ThingInformation:
        """
        Fetch `Thing` instance's own information (some useful metadata which helps the `Thing` run).

        Highly unused and irrelevant currently.

        Returns
        -------
        `ThingInformation`

        Raises
        ------
        DatabaseError
        """
        if not inspect_database(self.engine).has_table("things"):
            return
        with self.sync_session() as session:
            stmt = select(ThingInformation).filter_by(
                thing_id=self.thing.id,
                thing_class=self.thing.__class__.__name__,
            )
            data = session.execute(stmt)
            data = data.scalars().all()
            if len(data) == 0:
                return None
            elif len(data) == 1:
                return data[0]
            else:  # TODO raise different exception?
                raise DatabaseError(
                    "Multiple things with same instance name found, either cleanup database/detach/make new"
                )

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
        DatabaseError
            if the property is not found in database or multiple properties with same name are found
        """
        with self.sync_session() as session:
            name = property if isinstance(property, str) else property.name
            stmt = select(SerializedProperty).filter_by(
                thing_id=self.thing.id,
                thing_class=self.thing.__class__.__name__,
                name=name,
            )
            data = session.execute(stmt)
            prop = data.scalars().all()  # type: list[SerializedProperty]
            if len(prop) == 0:
                raise DatabaseError(f"property {name} not found in database")
            elif len(prop) > 1:
                raise DatabaseError("multiple properties with same name found")  # Impossible actually
            if not deserialized:
                return prop[0]
            serializer = Serializers.content_types.get(prop[0].content_type, None) or Serializers.for_object(
                self.thing.id,
                self.thing.__class__.__name__,
                name,
            )
            return serializer.loads(prop[0].serialized_value)

    def set_property(self, property: str | Property, value: Any) -> None:
        """
        Change the value of an already existing property in the database.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        value: Any
            value of the property

        Raises
        ------
        DatabaseError
            if multiple properties with same name are found
        """
        name = property if isinstance(property, str) else property.name
        if self.in_batch_call_context:
            self._batch_call_context[threading.get_ident()][name] = value
            return
        with self.sync_session() as session:
            stmt = select(SerializedProperty).filter_by(
                thing_id=self.thing.id,
                thing_class=self.thing.__class__.__name__,
                name=name,
            )
            data = session.execute(stmt)
            prop = data.scalars().all()
            if len(prop) > 1:
                raise DatabaseError("multiple properties with same name found")  # Impossible actually
            if len(prop) == 1:
                prop = prop[0]
                serializer = Serializers.content_types.get(prop.content_type, None) or Serializers.for_object(
                    self.thing.id,
                    self.thing.__class__.__name__,
                    name,
                )
                prop.serialized_value = serializer.dumps(value)
                prop.updated_at = datetime.now().isoformat()
                prop.content_type = serializer.content_type
            else:
                serializer = Serializers.for_object(
                    self.thing.id,
                    self.thing.__class__.__name__,
                    name,
                )
                now = datetime.now().isoformat()
                prop = SerializedProperty(
                    id=None,  # ty: ignore[invalid-argument-type]
                    name=name,
                    serialized_value=serializer.dumps(value),
                    thing_id=self.thing.id,
                    thing_class=self.thing.__class__.__name__,
                    created_at=now,
                    updated_at=now,
                    content_type=serializer.content_type,
                )
                session.add(prop)
            session.commit()

    def get_properties(self, properties: dict[str | Property, Any], deserialized: bool = True) -> dict[str, Any]:
        """
        Get multiple properties at once from the database.

        Parameters
        ----------
        properties: List[str | Property]
            string names or the descriptor of the properties as a list
        deserialized: bool, default True
            deserilize the properties if True

        Returns
        -------
        dict[str, Any]
            property names and values as items
        """
        with self.sync_session() as session:
            names = []
            for obj in properties.keys():
                names.append(obj if isinstance(obj, str) else obj.name)
            stmt = (
                select(SerializedProperty)
                .filter_by(
                    thing_id=self.thing.id,
                    thing_class=self.thing.__class__.__name__,
                )
                .filter(SerializedProperty.name.in_(names))
            )
            data = session.execute(stmt)
            unserialized_props = data.scalars().all()
            props = dict()
            for prop in unserialized_props:
                serializer = Serializers.content_types.get(prop.content_type, None) or Serializers.for_object(
                    self.thing.id,
                    self.thing.__class__.__name__,
                    prop.name,
                )
                props[prop.name] = (
                    prop.serialized_value if not deserialized else serializer.loads(prop.serialized_value)
                )
            return props

    def set_properties(self, properties: dict[str | Property, Any]) -> None:
        """
        Change the values of already existing properties at once in the database.

        Parameters
        ----------
        properties: Dict[str | Property, Any]
            string names or the descriptor of the property and any value as dictionary pairs

        Raises
        ------
        DatabaseError
            if multiple properties with same name are found
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
                .filter_by(
                    thing_id=self.thing.id,
                    thing_class=self.thing.__class__.__name__,
                )
                .filter(SerializedProperty.name.in_(names))
            )
            data = session.execute(stmt)
            db_props = data.scalars().all()
            for obj, value in properties.items():
                name = obj if isinstance(obj, str) else obj.name
                db_prop = list(filter(lambda db_prop: db_prop.name == name, db_props))  # type: list[SerializedProperty]
                if len(db_prop) > 1:
                    raise DatabaseError("multiple properties with same name found")  # Impossible actually
                if len(db_prop) == 1:
                    db_prop = db_prop[0]  # type: SerializedProperty
                    serializer = Serializers.content_types.get(db_prop.content_type, None) or Serializers.for_object(
                        self.thing.id,
                        self.thing.__class__.__name__,
                        name,
                    )
                    db_prop.serialized_value = serializer.dumps(value)
                    db_prop.updated_at = datetime.now().isoformat()
                    db_prop.content_type = serializer.content_type
                else:
                    serializer = Serializers.for_object(
                        self.thing.id,
                        self.thing.__class__.__name__,
                        name,
                    )
                    now = datetime.now().isoformat()
                    prop = SerializedProperty(
                        id=None,  # ty: ignore[invalid-argument-type]
                        name=name,
                        serialized_value=serializer.dumps(value),
                        thing_id=self.thing.id,
                        thing_class=self.thing.__class__.__name__,
                        created_at=now,
                        updated_at=now,
                        content_type=serializer.content_type,
                    )
                    session.add(prop)
            session.commit()

    def get_all_properties(self, deserialized: bool = True) -> dict[str, Any] | Sequence[SerializedProperty]:
        """
        Get all properties stored in the database.

        Parameters
        ----------
        deserialized: bool, default True
            deserilize the properties if True

        Returns
        -------
        dict[str, Any]
            property names and values as items
        """
        with self.sync_session() as session:
            stmt = select(SerializedProperty).filter_by(
                thing_id=self.thing.id,
                thing_class=self.thing.__class__.__name__,
            )
            data = session.execute(stmt)
            existing_props = data.scalars().all()  # type: list[SerializedProperty]
            if not deserialized:
                return existing_props
            props = dict()
            for prop in existing_props:
                serializer = Serializers.content_types.get(prop.content_type, None) or Serializers.for_object(
                    self.thing.id,
                    self.thing.__class__.__name__,
                    prop.name,
                )
                props[prop.name] = serializer.loads(prop.serialized_value)
            return props

    def create_missing_properties(
        self,
        properties: dict[str, Property],
        get_missing_property_names: bool = False,
    ) -> None | list[str]:
        """
        Create any and all missing properties in the database.

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
        with self.sync_session() as session:
            existing_props = self.get_all_properties()
            for prop in properties.values():
                if prop.name not in existing_props:
                    serializer = Serializers.for_object(
                        self.thing.id,
                        self.thing.__class__.__name__,
                        prop.name,
                    )
                    now = datetime.now().isoformat()
                    prop = SerializedProperty(
                        id=None,  # ty: ignore[invalid-argument-type]
                        name=prop.name,
                        serialized_value=serializer.dumps(getattr(self.thing, prop.name)),
                        thing_id=self.thing.id,
                        thing_class=self.thing.__class__.__name__,
                        created_at=now,
                        updated_at=now,
                        content_type=serializer.content_type,
                    )
                    session.add(prop)
                    missing_props.append(prop.name)
            session.commit()
        if get_missing_property_names:
            return missing_props

    def create_init_properties(self, thing_id: str, thing_class: str, **properties: Any) -> None:
        """
        Create properties that are supposed to be initialized from database for a thing instance.

        Invoke this method once before running the thing instance to store its initial value.

        Parameters
        ----------
        thing_id: str
            ID of the thing instance to which these properties belong
        thing_class: str
            Class name of the thing instance to which these properties belong
        properties: dict[str, Any]
            property names and their initial values as dictionary pairs
        """
        with self.sync_session() as session:
            for name, value in properties.items():
                serializer = Serializers.for_object(thing_id, thing_class, name)
                now = datetime.now().isoformat()
                prop = SerializedProperty(
                    id=None,  # ty: ignore[invalid-argument-type]
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
    Write multiple properties to a database at once.

    Useful for optimizing sequential sets/writes of multiple properties which are stored onto a database.
    """

    def __init__(self, db_engine: SQLAlchemyDB) -> None:
        self.db_engine = db_engine

    def __enter__(self) -> None:
        self.db_engine._batch_call_context[threading.get_ident()] = dict()

    def __exit__(self, exc_type, exc_value, exc_tb) -> None:
        data = self.db_engine._batch_call_context.pop(threading.get_ident(), dict())
        if exc_type is None:
            self.db_engine.set_properties(data)
            return
        for name, value in data.items():
            try:
                self.db_engine.set_property(name, value)
            except Exception as ex:
                self.db_engine.thing.logger.error(
                    f"failed to set property {name} to value {value} during batch commit due to exception {ex}"
                )


__all__ = [
    # BaseAsyncDB.__name__,
    BaseSyncDB.__name__,
    SQLAlchemyDB.__name__,
    batch_db_commit.__name__,
]
