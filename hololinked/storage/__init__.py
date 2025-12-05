import os

from ..config import global_config
from ..utils import get_sanitized_filename_from_random_string
from .database import MongoThingDB, ThingDB
from .json_storage import ThingJSONStorage


def prepare_object_storage(instance, **kwargs):
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
    db_config_file = kwargs.get("db_config_file", None)

    if use_json_file:
        json_filename = kwargs.get(
            "json_filename",
            f"{get_sanitized_filename_from_random_string(f'{instance.__class__.__name__}_{instance.id}', extension='json')}",
        )
        json_filename = os.path.join(global_config.TEMP_DIR_db, json_filename)
        instance.db_engine = ThingJSONStorage(filename=json_filename, instance=instance)
        instance.logger.info(f"using JSON file storage at {json_filename}")
    elif use_mongo:
        instance.db_engine = MongoThingDB(instance=instance, config_file=db_config_file)
        instance.logger.info("using MongoDB storage")
    elif use_default_db or db_config_file:
        instance.db_engine = ThingDB(instance=instance, config_file=db_config_file)
        instance.logger.info("using SQLAlchemy based storage")
