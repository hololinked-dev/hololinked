"""
Validators for validating data against schemas.

All of properties, actions and events validate can their payload or types against the schema.
For properties and actions, validation is carried out right before carrying out the operation.
For events, such validation is missing on the client. For properties and actions, said validation is also missing
on the client. This is an architectural error that needs to be fixed. The current architecture of the package leads
to duplication of code if this is implemented as is. Therefore it has been left out by choice.
"""

from typing import TYPE_CHECKING

from hololinked.utils import lazy_module_getattr


__all__ = [
    "FastJSONSchemaValidator",
    "JSONSchemaValidator",
    "PydanticSchemaValidator",
]

_lazy: dict[str, str] = {
    "JSONSchemaValidator": ".json_schema",
    "PydanticSchemaValidator": ".pydantic_model",
    "FastJSONSchemaValidator": ".fast_json_schema",
}
"""Name of a schema validator mapped to the module it is imported from, resolved lazily."""

__getattr__ = lazy_module_getattr(__name__, _lazy, globals())


if TYPE_CHECKING:
    from .fast_json_schema import FastJSONSchemaValidator as FastJSONSchemaValidator
    from .json_schema import JSONSchemaValidator as JSONSchemaValidator
    from .pydantic_model import PydanticSchemaValidator as PydanticSchemaValidator
