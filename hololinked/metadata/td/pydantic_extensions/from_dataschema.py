"""Convert Thing Description DataSchemas to Python types and pydantic models (TD to code)."""

from __future__ import annotations

import warnings

from collections.abc import Callable
from types import GenericAlias
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model

from hololinked.utils import ModelRoot, issubklass

from .to_dataschema import check_recursion, look_up_reference


PRIMITIVE_TYPES: dict[str, type | None] = {
    "null": None,
    "boolean": bool,
    "integer": int,
    "number": float,
    "string": str,
}

# keywords with no validation meaning, ignored without a warning
ANNOTATION_KEYWORDS = frozenset({"unit", "readOnly", "writeOnly", "format", "$comment"})

NUMBER_CONSTRAINTS = {
    "minimum": "ge",
    "maximum": "le",
    "exclusiveMinimum": "gt",
    "exclusiveMaximum": "lt",
    "multipleOf": "multiple_of",
}
# JSON schema keyword to pydantic Field argument, per type the keyword applies to
CONSTRAINTS: dict[str, dict[str, str]] = {
    "integer": NUMBER_CONSTRAINTS,
    "number": NUMBER_CONSTRAINTS,
    "string": {"minLength": "min_length", "maxLength": "max_length", "pattern": "pattern"},
    "array": {"minItems": "min_length", "maxItems": "max_length"},
}


class DataSchemaRoot(ModelRoot):
    """Root model of non-object DataSchemas."""

    model_config = ConfigDict(arbitrary_types_allowed=True, regex_engine="python-re")
    # JSON schema patterns are ECMA 262 regexes. Python's re supports lookarounds and backreferences like them,
    # pydantic's default rust regex engine does not.


def dataschema_to_model(
    schema: dict[str, Any],
    name: str,
    strict: bool = False,
    root: dict[str, Any] | None = None,
) -> type[BaseModel]:
    """
    Convert a Thing Description DataSchema to a pydantic model, the reverse of `type_to_dataschema`.

    Parameters
    ----------
    schema: dict[str, Any]
        the DataSchema to convert
    name: str
        name of the generated model
    strict: bool
        raise instead of warn when the schema contains a unsupported keyword
    root: dict[str, Any] | None
        document that local `$ref`s resolve against, for example the whole TD; defaults to `schema`

    Returns
    -------
    type[BaseModel]
        the model of an object schema, otherwise a `RootModel` wrapping the Python type of the schema

    Raises
    ------
    TypeError
        if `strict` is set and the schema contains an unsupported keyword
    NotImplementedError
        if the schema type is not supported yet
    ValueError
        if no value of an enum or const satisfies the constraints next to it, a default does not validate, or a
        `$ref` is circular
    KeyError
        if a `$ref` does not point to a schema in the document
    """
    python_type = dataschema_to_type(schema, strict=strict, name=name, root=root)
    if issubklass(python_type, BaseModel):
        return python_type
    return create_model(name, root=(python_type, ...), __base__=DataSchemaRoot)


def dataschema_to_type(
    schema: dict[str, Any],
    strict: bool = False,
    location: str = "#",
    name: str = "Model",
    root: dict[str, Any] | None = None,
    depth: int = 0,
) -> Any:
    """
    Convert a Thing Description DataSchema to the equivalent Python type.

    Parameters
    ----------
    schema: dict[str, Any]
        the DataSchema to convert
    strict: bool
        raise instead of warn when the schema contains an unsupported keyword
    location: str
        JSON pointer of `schema` within the root schema, used in warnings and errors
    name: str
        name of the model generated for an object schema, nested models are named after it
    root: dict[str, Any] | None
        document that local `$ref`s resolve against; defaults to `schema`
    depth: int
        nesting depth of `schema`, which stops circular references

    Returns
    -------
    Any
        the Python type

    Raises
    ------
    TypeError
        if `strict` is set and the schema contains an unsupported keyword
    NotImplementedError
        if the schema type is not supported yet
    ValueError
        if no value of an enum or const satisfies the constraints next to it, a default does not validate, or a
        `$ref` is circular
    KeyError
        if a `$ref` does not point to a schema in the document
    """
    root = schema if root is None else root
    check_recursion(depth, 99)

    def convert(subschema: dict[str, Any], pointer: str, suffix: Any) -> Any:
        return dataschema_to_type(
            subschema, strict, location=f"{location}/{pointer}", name=f"{name}_{suffix}", root=root, depth=depth + 1
        )

    if "$ref" in schema:
        # keywords next to $ref apply together with the referenced schema
        reference = schema["$ref"]
        merged = {**look_up_reference(reference, root), **{k: v for k, v in schema.items() if k != "$ref"}}
        return dataschema_to_type(merged, strict, location=reference, name=name, root=root, depth=depth + 1)

    schema_type = schema.get("type")
    handled = {"type", "$defs", "definitions"}  # definitions only hold schemas for $ref
    # title(s), description(s) and default only document a schema, so they are written back unchanged
    annotations = {
        key: schema[key] for key in ("title", "titles", "description", "descriptions", "default") if key in schema
    }
    handled.update(annotations)
    constraint_keywords = CONSTRAINTS.get(schema_type, {}) if isinstance(schema_type, str) else {}
    union_key = next((key for key in ("oneOf", "anyOf") if key in schema), None)
    if schema_type is None and union_key:
        # a Union accepts a value matching any option; oneOf's "exactly one" cannot be expressed, but TD
        # generation writes pydantic's anyOf as oneOf, so oneOf in a TD usually means anyOf anyway
        handled.add(union_key)
        options = tuple(
            convert(option, f"{union_key}/{index}", index) for index, option in enumerate(schema[union_key])
        )
        python_type = Union.__getitem__(options)
    elif schema_type is None:
        python_type = Any
    elif schema_type == "array" and ("prefixItems" in schema or isinstance(schema.get("items"), list)):
        # JSON schema 2020 uses prefixItems, TD (JSON schema 2019) uses a list of items
        key = "prefixItems" if "prefixItems" in schema else "items"
        handled.add(key)
        item_types = tuple(convert(item, f"{key}/{index}", index) for index, item in enumerate(schema[key]))
        python_type = GenericAlias(tuple, item_types)
        constraint_keywords = {}
        # a tuple has a fixed length, so length limits equal to it and no additional items are implied
        handled.update(k for k in ("minItems", "maxItems") if schema.get(k) == len(item_types))
        if key == "prefixItems" and schema.get("items") is False:
            handled.add("items")
    elif schema_type == "array":
        handled.add("items")
        python_type = GenericAlias(list, (convert(schema.get("items", {}), "items", "items"),))
    elif schema_type == "object" and not ({"properties", "required"} & set(schema)):
        # an object without named fields is a dictionary, unless additionalProperties forbids every key
        handled.add("additionalProperties")
        additional = schema.get("additionalProperties", True)
        if additional is False:
            python_type = create_model(
                name,
                __config__=ConfigDict(
                    extra="forbid",
                    json_schema_extra=restore_schema_annotations(annotations),
                    regex_engine="python-re",
                ),
            )
        else:
            value_type = convert(additional if isinstance(additional, dict) else {}, "additionalProperties", "values")
            python_type = GenericAlias(dict, (str, value_type))
    elif schema_type == "object":
        handled.update(("properties", "required", "additionalProperties"))
        required = schema.get("required", [])
        fields: dict[str, Any] = {}
        for key, subschema in schema.get("properties", {}).items():
            field_type = convert(subschema, f"properties/{key}", key)
            if key in required:
                fields[key] = (field_type, ...)
            elif "default" in subschema:
                fields[key] = (field_type, Field(default=subschema["default"]))
            else:
                # an absent field is not a default, so the None placeholder is neither validated nor in the schema
                fields[key] = (
                    field_type,
                    Field(
                        default=None,
                        validate_default=False,
                        json_schema_extra=lambda schema: schema.pop("default", None),
                    ),
                )
        for key in required:
            fields.setdefault(key, (Any, ...))  # required without a schema accepts any value
        # unlike JSON schema, fields not listed are forbidden unless additionalProperties allows them
        additional = schema.get("additionalProperties", False)
        if additional is not False:
            value_type = convert(additional if isinstance(additional, dict) else {}, "additionalProperties", "values")
            fields["__pydantic_extra__"] = (GenericAlias(dict, (str, value_type)), ...)
        python_type = create_model(
            name,
            __config__=ConfigDict(
                extra="forbid" if additional is False else "allow",
                json_schema_extra=restore_schema_annotations(annotations),
                regex_engine="python-re",
                validate_default=True,  # e.g. a nested object's default becomes a model instance
            ),
            **fields,
        )
    elif isinstance(schema_type, str) and schema_type in PRIMITIVE_TYPES:
        python_type = PRIMITIVE_TYPES[schema_type]
    else:
        raise NotImplementedError(f"DataSchema type {schema_type!r} at {location} is not supported yet")
    constraints = {field: schema[keyword] for keyword, field in constraint_keywords.items() if keyword in schema}
    if constraints:
        handled.update(keyword for keyword in constraint_keywords if keyword in schema)
        python_type = Annotated[python_type, Field(**constraints)]  # ty: ignore[invalid-type-form]
    # const and enum narrow the type to the listed values; Literal compares by value, so any JSON value works
    values: tuple | None = None
    if "const" in schema:
        handled.add("const")
        if "enum" in schema and schema["const"] in schema["enum"]:
            handled.add("enum")
        values = (schema["const"],)
    elif "enum" in schema:
        handled.add("enum")
        values = tuple(schema["enum"])
    if values is not None:
        if constraints:
            # pydantic cannot write constraints on a Literal back to JSON schema, so they filter the values instead
            adapter = type_adapter(python_type)
            values = tuple(value for value in values if value_validates(adapter, value))
            if not values:
                raise ValueError(f"No value of enum or const at {location} satisfies the constraints {constraints}")
        python_type = Literal.__getitem__(values)
    if "default" in schema and not value_validates(type_adapter(python_type), schema["default"]):
        # pydantic validates a default only when it is used, so a broken TD would fail requests instead
        raise ValueError(f"Default {schema['default']!r} at {location}/default does not validate against its schema")
    if annotations and not issubklass(python_type, BaseModel):  # models carry them in their own schema
        python_type = Annotated[python_type, Field(json_schema_extra=annotations)]  # ty: ignore[invalid-type-form]
    unsupported = sorted(set(schema) - handled - ANNOTATION_KEYWORDS)
    if unsupported:
        message = f"DataSchema keywords {unsupported} at {location} cannot be expressed in pydantic"
        if strict:
            raise TypeError(message)
        warnings.warn(f"{message} and are ignored", UserWarning, stacklevel=2)
    return python_type


def type_adapter(python_type: Any) -> TypeAdapter:
    """
    Create a `TypeAdapter` validating like the models generated from DataSchemas.

    Parameters
    ----------
    python_type: Any
        a type returned by `dataschema_to_type`

    Returns
    -------
    TypeAdapter
        adapter for `python_type`
    """
    if issubklass(python_type, BaseModel):
        return TypeAdapter(python_type)  # a model brings its own config
    return TypeAdapter(python_type, config=ConfigDict(regex_engine="python-re"))


def value_validates(adapter: TypeAdapter, value: Any) -> bool:
    """
    Check whether a value validates, without raising.

    Parameters
    ----------
    adapter: TypeAdapter
        adapter of the type to validate against
    value: Any
        the value to validate

    Returns
    -------
    bool
        `True` if the value is valid, `False` otherwise
    """
    try:
        adapter.validate_python(value)
        return True
    except ValidationError:
        return False


def restore_schema_annotations(annotations: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    """
    Create a `json_schema_extra` hook writing the DataSchema's own annotations into a generated model's schema.

    Parameters
    ----------
    annotations: dict[str, Any]
        the title(s), description(s) and default of the DataSchema

    Returns
    -------
    Callable[[dict[str, Any]], None]
        hook replacing the generated title with `annotations`
    """

    def json_schema_extra(schema: dict[str, Any]) -> None:
        schema.pop("title", None)  # the generated model name, not part of the DataSchema
        schema.update(annotations)

    return json_schema_extra
