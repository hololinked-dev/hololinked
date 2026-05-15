"""Dependency injection for configurable storage backends."""

from __future__ import annotations

import os

from typing import TYPE_CHECKING

from hololinked.config import global_config
from hololinked.storage.jsonfile import JSONFileStorage
from hololinked.storage.mongodb import MongoDB
from hololinked.storage.sqlalchemydb import SQLAlchemyDB
from hololinked.utils import get_sanitized_filename_from_random_string


if TYPE_CHECKING:
    from hololinked.core.thing import Thing


def prepare_object_storage(thing: Thing, **kwargs) -> None:
    """
    Prepare the storage backend for a `Thing` instance.

    Parameters
    ----------
    thing: Thing
        The `Thing` instance to prepare storage for
    kwargs:
        Additional keyword arguments to configure storage backend

        - `use_json_file`: `bool`, whether to use JSON file storage (default: False)
        - `use_default_db`: `bool`, whether to use default SQLite database storage (default: False)
        - `use_mongo_db`: `bool`, whether to use MongoDB storage (default: False)
        - `db_config_file`: `str`, path to database configuration file (default: from `global_config.DB_CONFIG_FILE`)
        - `json_filename`: `str`, filename for JSON file storage (default: derived from thing instance)
    """
    use_json_file = kwargs.get(
        "use_json_file",
        thing.__class__.use_json_file if hasattr(thing.__class__, "use_json_file") else False,
    )
    use_default_db = kwargs.get(
        "use_default_db",
        thing.__class__.use_default_db if hasattr(thing.__class__, "use_default_db") else False,
    )
    use_mongo = kwargs.get(
        "use_mongo_db",
        thing.__class__.use_mongo_db if hasattr(thing.__class__, "use_mongo_db") else False,
    )
    db_config_file = kwargs.get("db_config_file", global_config.DB_CONFIG_FILE)

    if use_json_file:
        json_filename = os.path.join(
            global_config.TEMP_DIR_DB,
            kwargs.get("json_filename", f"{get_sanitized_filename_from_random_string(thing.id, extension='json')}"),
        )
        json_filename = os.path.join(global_config.TEMP_DIR_DB, json_filename)
        thing.db_engine = JSONFileStorage(filename=json_filename, thing=thing)  # serializer= # TODO
        thing.logger.info(f"using JSON file storage at {json_filename}")
    elif use_mongo:
        thing.db_engine = MongoDB(thing=thing, config_file=db_config_file)
        thing.logger.info("using MongoDB storage")
    elif use_default_db or db_config_file:
        thing.db_engine = SQLAlchemyDB(thing=thing, config_file=db_config_file)
        thing.logger.info("using SQLAlchemy based storage")
