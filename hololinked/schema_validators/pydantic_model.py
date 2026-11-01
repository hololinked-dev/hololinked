"""Schema validator based on pydantic models."""

from __future__ import annotations

import typing

from collections.abc import Mapping
from functools import cached_property
from typing import Any, Literal

import pydantic

from pydantic import BaseModel, RootModel

from hololinked.constants import JSONSchemaType
from hololinked.core.exceptions import ValidationError
from hololinked.core.interfaces import BaseSchemaValidator
from hololinked.utils import issubklass, wrap_plain_types_in_rootmodel

from .utils import pydantic_validate_args_kwargs, pydantic_validation_error_message


class PydanticSchemaValidator(BaseSchemaValidator):
    """
    Pydantic model validator.

    ```python
    class PowerSupplyOutput(BaseModel):
        current: float = Field(..., ge=0)
        power: float = Field(..., ge=0, le=100)

    validator = PydanticSchemaValidator(PowerSupplyOutput)
    validator.validate({"current": 50, "power": 75})  # valid
    validator.validate({"current": 65, "power": 110})  # raises
    ```

    The user is encouraged to use pydantic models as much as possible. This class is largely used internally and
    there is no need to explicitly instantiate it.
    """

    schema: type[BaseModel]

    def __init__(self, schema: type[BaseModel]) -> None:
        """
        Initialize the validator.

        Parameters
        ----------
        schema: type[BaseModel]
            The pydantic model to validate against
        """
        super().__init__(schema)
        self.validator = schema.model_validate

    @classmethod
    def from_type(cls, type_: Any) -> PydanticSchemaValidator:
        """
        Create a validator for a plain type or typing form, such as `int` or `list[int]`, wrapped in a root model.

        Parameters
        ----------
        type_: Any
            the type to validate against, a pydantic model is used as it is

        Returns
        -------
        PydanticSchemaValidator
            the validator, whose `schema` is the root model
        """
        return cls(wrap_plain_types_in_rootmodel(type_))

    @cached_property
    def input_kind(self) -> Literal["fields", "mapping", "value"]:
        """
        How the arguments of a method call make up the value validated against the model.

        - `fields`: a regular model, each argument is validated as the field of the same name
        - `mapping`: a root model wrapping a mapping or another model, all keyword arguments are collected
          into one dict and validated as the root
        - `value`: a root model wrapping any other type, the call takes exactly one argument, which is validated
          as the root
        """
        if not issubklass(self.schema, RootModel):
            return "fields"
        root_type = self.schema.model_fields["root"].annotation
        root_type = typing.get_origin(root_type) or root_type
        return "mapping" if issubklass(root_type, (Mapping, BaseModel)) else "value"

    def validate(self, data) -> Any:
        """
        Validate the data against the model.

        Returns
        -------
        Any
            the model instance, or the value it wraps for a root model, like `3` for a root model of `int`

        Raises
        ------
        ValidationError
            if the data does not conform to the model
        """
        try:
            value = self.validator(data)
        except pydantic.ValidationError as ex:
            raise ValidationError(pydantic_validation_error_message(ex)) from ex
        return value.root if isinstance(value, RootModel) else value

    def validate_method_call(self, args, kwargs) -> None:  # noqa: D102
        try:
            if self.input_kind == "value":
                values = [*args, *kwargs.values()]
                if len(values) != 1:
                    raise ValidationError(f"Expected exactly one argument, given {len(values)}.")
                self.validator(values[0])
            elif self.input_kind == "mapping":
                if args:
                    raise ValidationError(
                        "Positional arguments are not accepted for an object input, give keyword arguments."
                    )
                self.validator(kwargs)
            else:
                pydantic_validate_args_kwargs(self.schema, args, kwargs)
        except pydantic.ValidationError as ex:
            raise ValidationError(pydantic_validation_error_message(ex)) from ex

    def json(self) -> JSONSchemaType:  # noqa: D102
        return self.schema.model_dump_json()  # ty: ignore[invalid-return-type, missing-argument]

    def __get_state__(self) -> JSONSchemaType:
        return self.json()

    def __set_state__(self, schema: JSONSchemaType):
        return PydanticSchemaValidator(BaseModel(**schema))  # ty: ignore[invalid-argument-type]
