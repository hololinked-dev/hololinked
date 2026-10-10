"""Helpers mapping the arguments of a method call onto the schema of its input."""

import typing

from collections import OrderedDict
from inspect import Parameter
from typing import Any

from pydantic import BaseModel


def pydantic_validate_args_kwargs(
    model: type[BaseModel],
    args: tuple = tuple(),
    kwargs: dict = dict(),
) -> None:
    """
    Validate and separate *args and **kwargs according to the fields of the given pydantic model.

    Parameters
    ----------
    model: Type[BaseModel]
        The pydantic model class to validate against.
    *args: tuple
        Positional arguments to validate.
    **kwargs: dict
        Keyword arguments to validate.

    Raises
    ------
    ValueError
        If the arguments do not match the model's fields.
    ValidationError
        If the arguments are invalid
    """
    field_names = list(model.model_fields.keys())
    data = {}

    # Assign positional arguments to the corresponding fields
    for i, arg in enumerate(args):
        if i >= len(field_names):
            raise ValueError(f"Too many positional arguments. Expected at most {len(field_names)}.")
        field_name = field_names[i]
        if Parameter.VAR_POSITIONAL in model.model_fields[field_name].metadata:
            if typing.get_origin(model.model_fields[field_name].annotation) is list:
                data[field_name] = list(args[i:])
            else:
                data[field_name] = args[i:]  # *args become end of positional arguments
            break
        elif field_name in data:
            raise ValueError(f"Multiple values for argument '{field_name}'.")
        data[field_name] = arg

    extra_kwargs = {}
    # Assign keyword arguments to the corresponding fields
    for key, value in kwargs.items():
        if key in data or key in extra_kwargs:  # Check for duplicate arguments
            raise ValueError(f"Multiple values for argument '{key}'.")
        if key in field_names:
            data[key] = value
        else:
            extra_kwargs[key] = value

    if extra_kwargs:
        for i in range(len(field_names)):
            if Parameter.VAR_KEYWORD in model.model_fields[field_names[i]].metadata:
                data[field_names[i]] = extra_kwargs
                break
            elif i == len(field_names) - 1:
                raise ValueError(f"Unexpected keyword arguments: {', '.join(extra_kwargs.keys())}")
    # Validate and create the model instance
    model.model_validate(data)


def json_schema_merge_args_to_kwargs(schema: dict, args: tuple = tuple(), kwargs: dict = dict()) -> dict[str, Any]:
    """
    Merge positional arguments into keyword arguments according to the schema.

    Parameters
    ----------
    schema: dict
        The JSON schema to validate against.
    args: tuple
        Positional arguments to merge.
    kwargs: dict
        Keyword arguments to merge.

    Returns
    -------
    dict
        The merged arguments as a dictionary, usually a JSON

    Raises
    ------
    ValueError
        if the schema is not an object, or the given arguments do not fit its properties
    """
    if not (schema.get("type") == "object" or "properties" in schema):
        raise ValueError("Schema must be an object.")

    field_names = list(OrderedDict(schema.get("properties", {})).keys())
    data = {}

    for i, arg in enumerate(args):
        if i >= len(field_names):
            raise ValueError(f"Too many positional arguments. Expected at most {len(field_names)}.")
        field_name = field_names[i]
        if field_name in data:
            raise ValueError(f"Multiple values for argument '{field_name}'.")
        data[field_name] = arg

    extra_kwargs = {}
    # Assign keyword arguments to the corresponding fields
    for key, value in kwargs.items():
        if key in data or key in extra_kwargs:  # Check for duplicate arguments
            raise ValueError(f"Multiple values for argument '{key}'.")
        if key in field_names:
            data[key] = value
        else:
            extra_kwargs[key] = value

    if extra_kwargs:
        data.update(extra_kwargs)
    return data
