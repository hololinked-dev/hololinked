"""beginner friendly data acquisition and IoT in python."""

__version__ = "0.4.0"

from .config import global_config  # noqa
from .serializer_registry import Serializers as Serializers
from .schema_registry import JSONSchema as JSONSchema

import hololinked.core  # noqa: F401
import hololinked.serializers  # noqa: F401
