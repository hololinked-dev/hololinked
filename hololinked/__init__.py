"""beginner friendly data acquisition and IoT in python."""

__version__ = "0.4.0"

from .config import global_config  # noqa
from .core.schema import JSONSchema as JSONSchema
from .injection import SchemaValidators as SchemaValidators, Serializers as Serializers
from .persistence import prepare_object_storage  # noqa

import hololinked.core  # noqa: F401 # this one is lazy for most part
