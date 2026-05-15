"""beginner friendly data acquisition and IoT in python."""

__version__ = "0.4.0"

from .config import global_config  # noqa
from .serialization import Serializers as Serializers
from .schemas import JSONSchema as JSONSchema, SchemaValidatorClasses as SchemaValidatorClasses
from .persistence import prepare_object_storage  # noqa

import hololinked.core  # noqa: F401 # this one is lazy for most part
import hololinked.serializers  # noqa: F401
import hololinked.schema_validators  # noqa: F401
