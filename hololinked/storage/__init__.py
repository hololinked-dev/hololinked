from .database import *
from .database import prepare_object_database
from .json_storage import ThingJsonStorage
from ..utils import get_a_filename_from_instance

def prepare_object_storage(instance, **kwargs):
    
    if kwargs.get('use_json_file', instance.__class__.use_json_file if hasattr(instance.__class__, 'use_json_file') else False):
        filename = kwargs.get('json_filename', f"{get_a_filename_from_instance(instance, extension='json')}")
        instance.db_engine = ThingJsonStorage(filename=filename, instance=instance)
    else:
        prepare_object_database(instance, kwargs.get('use_default_db', False), kwargs.get('db_config_file', None))   
        