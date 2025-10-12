from .database import ThingDB, MongoThingDB
from .json_storage import ThingJSONStorage
from ..utils import get_a_filename_from_instance


def prepare_object_storage(instance, **kwargs):
    use_json_file = kwargs.get(
        "use_json_file", instance.__class__.use_json_file if hasattr(instance.__class__, "use_json_file") else False
    )
    use_mongo = kwargs.get(
        "use_mongo_db", instance.__class__.use_mongo_db if hasattr(instance.__class__, "use_mongo_db") else False
    )
    json_filename = kwargs.get("json_filename", f"{get_a_filename_from_instance(instance, extension='json')}")
    use_default_db = kwargs.get(
        "use_default_db", instance.__class__.use_default_db if hasattr(instance.__class__, "use_default_db") else False
    )
    db_config_file = kwargs.get("db_config_file", None)

    if use_json_file:
        instance.db_engine = ThingJSONStorage(filename=json_filename, instance=instance)
    elif use_mongo:
        config_file = kwargs.get("db_config_file", None)
        instance.db_engine = MongoThingDB(instance=instance, config_file=config_file)
    elif use_default_db or db_config_file:
        instance.db_engine = ThingDB(instance=instance, config_file=db_config_file)
