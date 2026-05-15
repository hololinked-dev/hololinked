"""Base class for all schema validators."""

from __future__ import annotations

from typing import Any

from hololinked.constants import JSONSchemaType


class BaseSchemaValidator:
    """
    Base class for all schema validators.

    Serves as a type definition.
    """

    def __init__(self, schema) -> None:
        self.schema = schema

    def validate(self, data: Any) -> None:
        """Validate the data against the schema."""
        raise NotImplementedError("validate method must be implemented by subclass")

    def validate_method_call(self, args: tuple[Any], kwargs: dict[str, Any]) -> None:
        """Validate the method call against the schema."""
        raise NotImplementedError("validate_method_call method must be implemented by subclass")

    def json(self) -> JSONSchemaType:
        """Allows JSON serialization of the validator instance itself."""
        raise NotImplementedError("json method must be implemented by subclass")

    def __get_state__(self) -> JSONSchemaType:
        return self.json()

    def __set_state__(self, schema: JSONSchemaType):
        raise NotImplementedError("__set_state__ method must be implemented by subclass")
