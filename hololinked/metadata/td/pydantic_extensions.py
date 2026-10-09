"""
pydantic specific utility functions for the TD module.

This module is largely copied from LabThings fast API.
Copyright belongs to LabThings, Richard Bowman and developers, licensed under MIT License.

MIT License

Copyright (c) 2024 Richard William Bowman

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import warnings

from collections.abc import Callable, Mapping, Sequence
from types import GenericAlias
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model
from pydantic._internal._core_utils import CoreSchemaOrField, is_core_schema
from pydantic.json_schema import GenerateJsonSchema

from hololinked.constants import JSONSchemaType
from hololinked.utils import ModelRoot, issubklass


AnyUri = str
Description = str
Descriptions = Optional[dict[str, str]]
Title = str
Titles = Optional[dict[str, str]]
Security = Union[list[str], str]
Scopes = Union[list[str], str]
TypeDeclaration = Union[str, list[str]]


def is_a_reference(d: JSONSchemaType) -> bool:
    """
    Return True if a JSONSchema dict is a reference.

    JSON Schema references are one-element dictionaries with
    a single key, `$ref`.  `pydantic` sometimes breaks this
    rule and so I don't check that it's a single key.

    Parameters
    ----------
    d: JSONSchemaType
        The JSONSchema dict to check

    Returns
    -------
    bool
        True if the dict is a reference, False otherwise
    """
    return "$ref" in d


def look_up_reference(reference: str, d: dict[str, Any]) -> dict[str, Any]:
    """
    Look up a reference in a JSONSchema.

    This first asserts the reference is local (i.e. starts with #
    so it's relative to the current file), then looks up
    each path component in turn.

    Parameters
    ----------
    reference: str
        The reference to look up, e.g. "#/components/schemas/MySchema"
    d: JSONSchemaType
        The JSONSchema dict to look up the reference in

    Returns
    -------
    JSONSchema
        The JSONSchema dict that the reference points to

    Raises
    ------
    NotImplementedError
        If the reference is not local (i.e. does not start with #)
    KeyError
        If the reference cannot be found in the JSONSchema
    """
    if not reference.startswith("#/"):
        raise NotImplementedError(
            "Built-in resolver can only dereference internal JSON references (i.e. starting with #)."
        )
    try:
        resolved: dict[str, Any] = d
        for key in reference[2:].split("/"):
            resolved = resolved[key]
        return resolved
    except KeyError as ke:
        raise KeyError(f"The JSON reference {reference} was not found in the schema (original error {ke}).")


def is_an_object(d: JSONSchemaType) -> bool:
    """
    Determine whether a JSON schema dict is an object.

    Parameters
    ----------
    d : JSONSchemaType
        The JSONSchema dict to check.

    Returns
    -------
    bool
        True if the dict represents an object type, False otherwise.
    """
    return "type" in d and d["type"] == "object"


def convert_object(d: JSONSchemaType) -> JSONSchemaType:
    """
    Convert an object from JSONSchema to Thing Description.

    Parameters
    ----------
    d : JSONSchemaType
        The JSONSchema dict representing an object.

    Returns
    -------
    JSONSchema
        The converted JSONSchema dict compatible with Thing Description.
    """
    out: JSONSchemaType = d.copy()
    # AdditionalProperties is not supported by Thing Description, and it is ambiguous
    # whether this implies it's false or absent. I will, for now, ignore it, so we
    # delete the key below.
    if "additionalProperties" in out:
        del out["additionalProperties"]
    return out


def convert_anyof(d: JSONSchemaType) -> JSONSchemaType:
    """
    Convert the anyof key to oneof.

    JSONSchema makes a distinction between "anyof" and "oneof", where the former
    means "any of these fields can be present" and the latter means "exactly one
    of these fields must be present". Thing Description does not have this
    distinction, so we convert anyof to oneof.

    Parameters
    ----------
    d : JSONSchemaType
        The JSONSchema dict to convert.

    Returns
    -------
    JSONSchema
        The converted JSONSchema dict with ``anyOf`` replaced by ``oneOf``.
    """
    if "anyOf" not in d:
        return d
    out: JSONSchemaType = d.copy()
    out["oneOf"] = out["anyOf"]
    del out["anyOf"]
    return out


def convert_prefixitems(d: JSONSchemaType) -> JSONSchemaType:
    """
    Convert the prefixitems key to items.

    JSONSchema 2019 (as used by thing description) used
    `items` with a list of values in the same way that JSONSchema
    now uses `prefixitems`.

    JSONSchema 2020 uses `items` to mean the same as `additionalItems`
    in JSONSchema 2019 - but Thing Description doesn't support the
    `additionalItems` keyword. This will result in us overwriting
    additional items, and we raise a ValueError if that happens.

    This behaviour may be relaxed in the future.

    Parameters
    ----------
    d : JSONSchemaType
        The JSONSchema dict to convert.

    Returns
    -------
    JSONSchemaType
        The converted JSONSchema dict with ``prefixItems`` replaced by ``items``.

    Raises
    ------
    ValueError
        If the ``items`` key already exists in the schema, as it would be overwritten.
    """
    if "prefixItems" not in d:
        return d
    out: JSONSchemaType = d.copy()
    if "items" in out:
        raise ValueError(f"Overwrote the `items` key on {out}.")
    out["items"] = out["prefixItems"]
    del out["prefixItems"]
    return out


def convert_additionalproperties(d: JSONSchemaType) -> JSONSchemaType:
    """
    Move additionalProperties into properties, or remove it.

    Parameters
    ----------
    d : JSONSchemaType
        The JSONSchema dict to convert.

    Returns
    -------
    JSONSchemaType
        The converted JSONSchema dict with ``additionalProperties`` moved or removed.
    """
    if "additionalProperties" not in d:
        return d
    out: dict[str, Any] = d.copy()  # type
    if "properties" in out and "additionalProperties" not in out["properties"]:
        out["properties"]["additionalProperties"] = out["additionalProperties"]
    del out["additionalProperties"]
    return out


def check_recursion(depth: int, limit: int):
    """
    Check the recursion count is less than the limit.

    Parameters
    ----------
    depth : int
        The current recursion depth.
    limit : int
        The maximum allowed recursion depth.

    Raises
    ------
    ValueError
        If the recursion depth exceeds the limit.
    """
    if depth > limit:
        raise ValueError(f"Recursion depth of {limit} exceeded - perhaps there is a circular reference?")


def jsonschema_to_dataschema(
    d: dict[str, Any],
    root_schema: dict[str, Any] | None = None,
    recursion_depth: int = 0,
    recursion_limit: int = 99,
) -> dict[str, Any]:
    """
    Remove references and change field formats.

    JSONSchema allows schemas to be replaced with `{"$ref": "#/path/to/schema"}`.
    Thing Description does not allow this. `dereference_jsonschema_dict` takes a
    `dict` representation of a JSON Schema document, and replaces all the
    references with the appropriate chunk of the file.

    JSONSchema can represent `Union` types using the `anyOf` keyword, which is
    called `oneOf` by Thing Description.  It's possible to achieve the same thing
    in the specific case of array elements, by setting `items` to a list of
    `DataSchema` objects. This function does not yet do that conversion.

    This generates a copy of the document, to avoid messing up `pydantic`'s cache.

    Parameters
    ----------
    d : JSONSchemaType
        The JSONSchema dict to convert.
    root_schema : JSONSchemaType, optional
        The root JSONSchema document used to resolve ``$ref`` references. Defaults to ``d``.
    recursion_depth : int, optional
        The current recursion depth, used to detect circular references. Defaults to 0.
    recursion_limit : int, optional
        The maximum allowed recursion depth. Defaults to 99.

    Returns
    -------
    JSONSchemaType
        The converted JSONSchema dict compatible with Thing Description.
    """
    root_schema = root_schema or d
    check_recursion(recursion_depth, recursion_limit)
    # JSONSchema references are one-element dictionaries, with a single key called $ref
    while is_a_reference(d):
        d = look_up_reference(d["$ref"], root_schema)
        recursion_depth += 1
        check_recursion(recursion_depth, recursion_limit)

    if is_an_object(d):
        d = convert_object(d)
    d = convert_anyof(d)
    d = convert_prefixitems(d)
    d = convert_additionalproperties(d)

    # After checking the object isn't a reference, we now recursively check
    # sub-dictionaries and dereference those if necessary. This could be done with a
    # comprehension, but I am prioritising readability over speed. This code is run when
    # generating the TD, not in time-critical situations.
    rkwargs: dict[str, Any] = {
        "root_schema": root_schema,
        "recursion_depth": recursion_depth + 1,
        "recursion_limit": recursion_limit,
    }
    output: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            # Any items that are Mappings (i.e. sub-dictionaries) must be recursed into
            output[k] = jsonschema_to_dataschema(v, **rkwargs)
        elif isinstance(v, Sequence) and len(v) > 0 and isinstance(v[0], Mapping):
            # We can also have lists of mappings (i.e. Array[DataSchema]), so we
            # recurse into these.
            output[k] = [jsonschema_to_dataschema(item, **rkwargs) for item in v if isinstance(item, dict)]
        else:
            output[k] = v
    return output


def type_to_dataschema(t: type | BaseModel, **kwargs) -> dict:
    """
    Convert a Python type to a Thing Description DataSchema.

    This makes use of pydantic's `schema_of` function to create a
    json schema, then applies some fixes to make a DataSchema
    as per the Thing Description (because Thing Description is
    almost but not quite compatible with JSONSchema).

    Additional keyword arguments are added to the DataSchema,
    and will override the fields generated from the type that
    is passed in. Typically you'll want to use this for the
    `title` field.

    Parameters
    ----------
    t: type or BaseModel
        The Python type or pydantic model to convert.
    **kwargs: dict[str, Any]
        Additional fields to merge into the resulting DataSchema, overriding any
        auto-generated values.

    Returns
    -------
    dict
        The Thing Description DataSchema representation of the given type.
    """
    if isinstance(t, BaseModel):
        json_schema = t.model_json_schema(schema_generator=GenerateJsonSchemaWithoutDefaultTitles)
    else:
        json_schema = TypeAdapter(t).json_schema(schema_generator=GenerateJsonSchemaWithoutDefaultTitles)
    if "title" in json_schema:
        # Remove the title if it was autogenerated from the class name
        if isinstance(t, type) and json_schema["title"] == t.__name__:
            del json_schema["title"]
    schema_dict = jsonschema_to_dataschema(json_schema)
    # Definitions of referenced ($ref) schemas are put in a
    # key called "definitions" or "$defs" by pydantic. We should delete this.
    # TODO: find a cleaner way to do this
    # This shouldn't be a severe problem: we will fail with a
    # validation error if other junk is left in the schema.
    for k in ["definitions", "$defs"]:
        if k in schema_dict:
            del schema_dict[k]
    schema_dict.update(kwargs)
    return schema_dict


class GenerateJsonSchemaWithoutDefaultTitles(GenerateJsonSchema):
    """Drops autogenerated titles from JSON Schema."""

    # https://stackoverflow.com/questions/78679812/pydantic-v2-to-json-schema-translation-how-to-suppress-autogeneration-of-title
    def field_title_should_be_set(self, schema: CoreSchemaOrField) -> bool:
        """
        Return False for core schemas to suppress autogenerated field titles.

        Parameters
        ----------
        schema: CoreSchemaOrField
            The pydantic core schema or field schema being evaluated.

        Returns
        -------
        bool
            False if the schema is a core schema and the parent would set a title,
            otherwise the parent class result.
        """
        return_value = super().field_title_should_be_set(schema)
        if return_value and is_core_schema(schema):
            return False
        return return_value


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
    """
    Root model of non-object DataSchemas.

    JSON schema patterns are ECMA 262 regexes. Python's re supports lookarounds and backreferences like them,
    pydantic's default rust regex engine does not.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, regex_engine="python-re")


def dataschema_to_model(
    schema: dict[str, Any], name: str, strict: bool = False, root: dict[str, Any] | None = None
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
                    extra="forbid", json_schema_extra=_annotate(annotations), regex_engine="python-re"
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
                    Field(default=None, validate_default=False, json_schema_extra=_drop_default),
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
                json_schema_extra=_annotate(annotations),
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
            adapter = _type_adapter(python_type)
            values = tuple(value for value in values if _is_valid(adapter, value))
            if not values:
                raise ValueError(f"No value of enum or const at {location} satisfies the constraints {constraints}")
        python_type = Literal.__getitem__(values)
    if "default" in schema and not _is_valid(_type_adapter(python_type), schema["default"]):
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


def _type_adapter(python_type: Any) -> TypeAdapter:
    if issubklass(python_type, BaseModel):
        return TypeAdapter(python_type)  # a model brings its own config
    return TypeAdapter(python_type, config=ConfigDict(regex_engine="python-re"))


def _is_valid(adapter: TypeAdapter, value: Any) -> bool:
    try:
        adapter.validate_python(value)
        return True
    except ValidationError:
        return False


def _drop_default(schema: dict[str, Any]) -> None:
    schema.pop("default", None)


def _annotate(annotations: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    def json_schema_extra(schema: dict[str, Any]) -> None:
        schema.pop("title", None)  # the generated model name, not part of the DataSchema
        schema.update(annotations)

    return json_schema_extra
