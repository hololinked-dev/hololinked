"""
Validators for validating data against schemas.

All of properties, actions and events validate can their payload or types against the schema.
For properties and actions, validation is carried out right before carrying out the operation.
For events, such validation is missing on the client. For properties and actions, said validation is also missing
on the client. This is an architectural error that needs to be fixed. The current architecture of the package leads
to duplication of code if this is implemented as is. Therefore it has been left out by choice.
"""

from typing import TYPE_CHECKING


__all__ = [
    "FastJSONSchemaValidator",
    "JSONSchemaValidator",
    "PydanticSchemaValidator",
]

_lazy: dict[str, tuple[str, str]] = {
    "JSONSchemaValidator": (".json_schema", "JSONSchemaValidator"),
    "PydanticSchemaValidator": (".pydantic_model", "PydanticSchemaValidator"),
    "FastJSONSchemaValidator": (".fast_json_schema", "FastJSONSchemaValidator"),
}


def __getattr__(name: str):
    if name not in _lazy:  # only lazy stuff for this adapter for now
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    module_path, attr = _lazy[name]
    mod = importlib.import_module(module_path, package=__name__)
    val = getattr(mod, attr)
    globals()[name] = val  # cache so subsequent access skips __getattr__
    return val


if TYPE_CHECKING:
    from .fast_json_schema import FastJSONSchemaValidator as FastJSONSchemaValidator
    from .json_schema import JSONSchemaValidator as JSONSchemaValidator
    from .pydantic_model import PydanticSchemaValidator as PydanticSchemaValidator
