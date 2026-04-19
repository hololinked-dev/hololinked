"""Models for ORM based storage."""

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import JSON, Integer, LargeBinary, String
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    mapped_column,
)

from ..constants import JSONSerializable


class ThingTableBase(DeclarativeBase):
    """SQLAlchemy base table for all `Thing` related tables."""

    pass


class SerializedProperty(MappedAsDataclass, ThingTableBase):
    """
    Represents a serialized property of a `Thing` instance stored in the database.

    Property Serialized is done, providing unified version for SQLite and other relational tables.
    Anyway while sending in the wire, the value is serialized to bytes, so when preserialized, the bytes
    are stored directly. A performance problem is not expected.
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
    """
    Stores information about the Thing instance itself.

    Useful metadata which may be later populated in a GUI or client applications need to go here.
    """

    __tablename__ = "things"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thing_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    thing_class: Mapped[str] = mapped_column(String, nullable=False)
    script: Mapped[str] = mapped_column(String)
    init_kwargs: Mapped[JSONSerializable] = mapped_column(JSON)
    server_id: Mapped[str] = mapped_column(String)

    def json(self) -> dict[str, Any]:
        """
        JSON-serializable dictionary representation of the Thing information.

        Returns
        -------
        dict[str, Any]
        """
        return asdict(self)


@dataclass
class DeserializedProperty:  # not part of database
    """Property with deserialized value after fetching from database."""

    thing_id: str
    name: str
    value: Any
    created_at: str
    updated_at: str
