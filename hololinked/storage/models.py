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
    """SQLAlchemy base table for all Thing related tables"""

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
    value: Any
    created_at: str
    updated_at: str
