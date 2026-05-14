"""Base class for all schema validators."""

from hololinked.constants import JSONSchema


class BaseSchemaValidator:
    """
    Base class for all schema validators.

    Serves as a type definition.
    """

    def __init__(self, schema) -> None:
        self.schema = schema

    def validate(self, data) -> None:
        """Validate the data against the schema."""
        raise NotImplementedError("validate method must be implemented by subclass")

    def validate_method_call(self, args, kwargs) -> None:
        """Validate the method call against the schema."""
        raise NotImplementedError("validate_method_call method must be implemented by subclass")

    def json(self) -> JSONSchema:
        """Allows JSON serialization of the validator instance itself."""
        raise NotImplementedError("json method must be implemented by subclass")

    def __get_state__(self):
        return self.json()

    def __set_state__(self, schema):
        raise NotImplementedError("__set_state__ method must be implemented by subclass")
