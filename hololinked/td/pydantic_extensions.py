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

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from pydantic import BaseModel, TypeAdapter
from pydantic._internal._core_utils import CoreSchemaOrField, is_core_schema
from pydantic.json_schema import GenerateJsonSchema


JSONSchema = dict[str, Any]  # A type to represent JSONSchema

AnyUri = str
Description = str
Descriptions = Optional[Dict[str, str]]
Title = str
Titles = Optional[Dict[str, str]]
Security = Union[List[str], str]
Scopes = Union[List[str], str]
TypeDeclaration = Union[str, List[str]]


def is_a_reference(d: JSONSchema) -> bool:
    """
    Return True if a JSONSchema dict is a reference.

    JSON Schema references are one-element dictionaries with
    a single key, `$ref`.  `pydantic` sometimes breaks this
    rule and so I don't check that it's a single key.

    Parameters
    ----------
    d: JSONSchema
        The JSONSchema dict to check

    Returns
    -------
    bool
        True if the dict is a reference, False otherwise
    """
    return "$ref" in d


def look_up_reference(reference: str, d: JSONSchema) -> JSONSchema:
    """
    Look up a reference in a JSONSchema.

    This first asserts the reference is local (i.e. starts with #
    so it's relative to the current file), then looks up
    each path component in turn.

    Parameters
    ----------
    reference: str
        The reference to look up, e.g. "#/components/schemas/MySchema"
    d: JSONSchema
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
        resolved: JSONSchema = d
        for key in reference[2:].split("/"):
            resolved = resolved[key]
        return resolved
    except KeyError as ke:
        raise KeyError(f"The JSON reference {reference} was not found in the schema (original error {ke}).")


def is_an_object(d: JSONSchema) -> bool:
    """Determine whether a JSON schema dict is an object.

    Parameters
    ----------
    d : JSONSchema
        The JSONSchema dict to check.

    Returns
    -------
    bool
        True if the dict represents an object type, False otherwise.
    """
    return "type" in d and d["type"] == "object"


def convert_object(d: JSONSchema) -> JSONSchema:
    """Convert an object from JSONSchema to Thing Description.

    Parameters
    ----------
    d : JSONSchema
        The JSONSchema dict representing an object.

    Returns
    -------
    JSONSchema
        The converted JSONSchema dict compatible with Thing Description.
    """
    out: JSONSchema = d.copy()
    # AdditionalProperties is not supported by Thing Description, and it is ambiguous
    # whether this implies it's false or absent. I will, for now, ignore it, so we
    # delete the key below.
    if "additionalProperties" in out:
        del out["additionalProperties"]
    return out


def convert_anyof(d: JSONSchema) -> JSONSchema:
    """
    Convert the anyof key to oneof.

    JSONSchema makes a distinction between "anyof" and "oneof", where the former
    means "any of these fields can be present" and the latter means "exactly one
    of these fields must be present". Thing Description does not have this
    distinction, so we convert anyof to oneof.

    Parameters
    ----------
    d : JSONSchema
        The JSONSchema dict to convert.

    Returns
    -------
    JSONSchema
        The converted JSONSchema dict with ``anyOf`` replaced by ``oneOf``.
    """
    if "anyOf" not in d:
        return d
    out: JSONSchema = d.copy()
    out["oneOf"] = out["anyOf"]
    del out["anyOf"]
    return out


def convert_prefixitems(d: JSONSchema) -> JSONSchema:
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
    d : JSONSchema
        The JSONSchema dict to convert.

    Returns
    -------
    JSONSchema
        The converted JSONSchema dict with ``prefixItems`` replaced by ``items``.

    Raises
    ------
    ValueError
        If the ``items`` key already exists in the schema, as it would be overwritten.
    """
    if "prefixItems" not in d:
        return d
    out: JSONSchema = d.copy()
    if "items" in out:
        raise ValueError(f"Overwrote the `items` key on {out}.")
    out["items"] = out["prefixItems"]
    del out["prefixItems"]
    return out


def convert_additionalproperties(d: JSONSchema) -> JSONSchema:
    """Move additionalProperties into properties, or remove it.

    Parameters
    ----------
    d : JSONSchema
        The JSONSchema dict to convert.

    Returns
    -------
    JSONSchema
        The converted JSONSchema dict with ``additionalProperties`` moved or removed.
    """
    if "additionalProperties" not in d:
        return d
    out: JSONSchema = d.copy()
    if "properties" in out and "additionalProperties" not in out["properties"]:
        out["properties"]["additionalProperties"] = out["additionalProperties"]
    del out["additionalProperties"]
    return out


def check_recursion(depth: int, limit: int):
    """Check the recursion count is less than the limit.

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
    d: JSONSchema,
    root_schema: Optional[JSONSchema] = None,
    recursion_depth: int = 0,
    recursion_limit: int = 99,
) -> JSONSchema:
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
    d : JSONSchema
        The JSONSchema dict to convert.
    root_schema : JSONSchema, optional
        The root JSONSchema document used to resolve ``$ref`` references. Defaults to ``d``.
    recursion_depth : int, optional
        The current recursion depth, used to detect circular references. Defaults to 0.
    recursion_limit : int, optional
        The maximum allowed recursion depth. Defaults to 99.

    Returns
    -------
    JSONSchema
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
    output: JSONSchema = {}
    for k, v in d.items():
        if isinstance(v, dict):
            # Any items that are Mappings (i.e. sub-dictionaries) must be recursed into
            output[k] = jsonschema_to_dataschema(v, **rkwargs)
        elif isinstance(v, Sequence) and len(v) > 0 and isinstance(v[0], Mapping):
            # We can also have lists of mappings (i.e. Array[DataSchema]), so we
            # recurse into these.
            output[k] = [jsonschema_to_dataschema(item, **rkwargs) for item in v]
        else:
            output[k] = v
    return output


def type_to_dataschema(t: Union[type, BaseModel], **kwargs) -> dict:
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
    t : type or BaseModel
        The Python type or pydantic model to convert.
    **kwargs : Any
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
        if json_schema["title"] == t.__name__:
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
        """Return False for core schemas to suppress autogenerated field titles.

        Parameters
        ----------
        schema : CoreSchemaOrField
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
