import os

from ..config import global_config
from .database import MongoThingDB, ThingDB
from .json_storage import ThingJSONStorage
from .utils import get_sanitized_filename_from_thing_instance


def prepare_object_storage(instance, **kwargs):
    """
    Prepare the storage backend for a `Thing` instance

    Parameters
    ----------
    instance:
        The `Thing` instance to prepare storage for
    kwargs:
        Additional keyword arguments to configure storage backend

        - `use_json_file`: `bool`, whether to use JSON file storage (default: False)
        - `use_default_db`: `bool`, whether to use default SQLite database storage (default: False)
        - `use_mongo_db`: `bool`, whether to use MongoDB storage (default: False)
        - `db_config_file`: `str`, path to database configuration file (default: from `global_config.DB_CONFIG_FILE`)
        - `json_filename`: `str`, filename for JSON file storage (default: derived from thing instance)

    Returns
    -------
    None
    """
    use_json_file = kwargs.get(
        "use_json_file",
        instance.__class__.use_json_file if hasattr(instance.__class__, "use_json_file") else False,
    )
    use_default_db = kwargs.get(
        "use_default_db",
        instance.__class__.use_default_db if hasattr(instance.__class__, "use_default_db") else False,
    )
    use_mongo = kwargs.get(
        "use_mongo_db",
        instance.__class__.use_mongo_db if hasattr(instance.__class__, "use_mongo_db") else False,
    )
    db_config_file = kwargs.get("db_config_file", global_config.DB_CONFIG_FILE)

    if use_json_file:
        json_filename = os.path.join(
            global_config.TEMP_DIR_DB,
            kwargs.get("json_filename", f"{get_sanitized_filename_from_thing_instance(instance, extension='json')}"),
        )
        json_filename = os.path.join(global_config.TEMP_DIR_DB, json_filename)
        instance.db_engine = ThingJSONStorage(filename=json_filename, instance=instance)
        instance.logger.info(f"using JSON file storage at {json_filename}")
    elif use_mongo:
        instance.db_engine = MongoThingDB(instance=instance, config_file=db_config_file)
        instance.logger.info("using MongoDB storage")
    elif use_default_db or db_config_file:
        instance.db_engine = ThingDB(instance=instance, config_file=db_config_file)
        instance.logger.info("using SQLAlchemy based storage")
