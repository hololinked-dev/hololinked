"""Schema validator based on pydantic models."""

import typing

from collections.abc import Mapping
from functools import cached_property
from typing import Literal

from pydantic import BaseModel, RootModel

from hololinked.constants import JSONSchemaType
from hololinked.core.interfaces import BaseSchemaValidator
from hololinked.utils import issubklass

from .utils import pydantic_validate_args_kwargs


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

    @cached_property
    def input_kind(self) -> Literal["fields", "mapping", "value"]:
        """
        How the arguments of a method call make up the value validated against the model.

        - `fields`: arguments map onto the fields of the model
        - `mapping`: a root model of a mapping or model, the keyword arguments together are the value
        - `value`: a root model of anything else, the single argument is the value
        """
        if not issubklass(self.schema, RootModel):
            return "fields"
        root_type = self.schema.model_fields["root"].annotation
        root_type = typing.get_origin(root_type) or root_type
        return "mapping" if issubklass(root_type, (Mapping, BaseModel)) else "value"

    def validate(self, data) -> None:  # noqa: D102
        self.validator(data)

    def validate_method_call(self, args, kwargs) -> None:  # noqa: D102
        if self.input_kind == "value":
            values = [*args, *kwargs.values()]
            if len(values) != 1:
                raise ValueError(f"Expected exactly one argument, given {len(values)}.")
            self.validator(values[0])
        elif self.input_kind == "mapping":
            if args:
                raise ValueError("Positional arguments are not accepted for an object input, give keyword arguments.")
            self.validator(kwargs)
        else:
            pydantic_validate_args_kwargs(self.schema, args, kwargs)

    def json(self) -> JSONSchemaType:  # noqa: D102
        return self.schema.model_dump_json()

    def __get_state__(self) -> JSONSchemaType:
        return self.json()

    def __set_state__(self, schema: JSONSchemaType):
        return PydanticSchemaValidator(BaseModel(**schema))  # ty: ignore[invalid-argument-type]
