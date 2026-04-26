"""Concrete implementations of schema validators."""

import jsonschema

from pydantic import BaseModel

from ..constants import JSONSchema
from ..utils import json_schema_merge_args_to_kwargs, pydantic_validate_args_kwargs


# type definition
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


class JSONSchemaValidator(BaseSchemaValidator):
    """
    JSON schema validator extending the standard python JSON schema package.

    ```python
    power_supply_output_schema = {
        "type": "object",
        "properties": {
            "current": {"type": "number", "minimum": 0},
            "power": {"type": "number", "minimum": 0, "maximum": 100},
        },
    }
    validator = JSONSchemaValidator(power_supply_output_schema)
    validator.validate({"current": 50, "power": 75})  # valid
    validator.validate({"current": 65, "power": 110})  # raises
    ```

    This class is largely used internally and there is no need to explicitly instantiate it.

    Consider `FastJSONSchemaValidator` (`pip install fastjsonschema`) or
    pydantic annotation based validation for performance if necessary.
    """

    def __init__(self, schema: JSONSchema) -> None:
        """
        Initialize the validator.

        Parameters
        ----------
        schema: JSONSchema
            The JSON schema to validate against
        """
        jsonschema.Draft7Validator.check_schema(schema)
        super().__init__(schema)
        self.validator = jsonschema.Draft7Validator(schema)

    def validate(self, data) -> None:  # noqa: D102
        self.validator.validate(data)

    def validate_method_call(self, args, kwargs) -> None:  # noqa: D102
        if len(args) > 0:
            kwargs = json_schema_merge_args_to_kwargs(self.schema, args, kwargs)
            # TODO fix type definition
        self.validate(kwargs)

    def json(self) -> JSONSchema:  # noqa: D102
        return self.schema

    def __get_state__(self):
        return self.schema

    def __set_state__(self, schema):
        return JSONSchemaValidator(schema)


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

    def __init__(self, schema: BaseModel) -> None:
        """
        Initialize the validator.

        Parameters
        ----------
        schema: BaseModel
            The pydantic model to validate against
        """
        super().__init__(schema)
        self.validator = schema.model_validate

    def validate(self, data) -> None:  # noqa: D102
        self.validator(data)

    def validate_method_call(self, args, kwargs) -> None:  # noqa: D102
        pydantic_validate_args_kwargs(self.schema, args, kwargs)

    def json(self) -> JSONSchema:  # noqa: D102
        return self.schema.model_dump_json()

    def __get_state__(self):
        return self.json()

    def __set_state__(self, schema: JSONSchema):
        return PydanticSchemaValidator(BaseModel(**schema))


try:
    import fastjsonschema

    class FastJSONSchemaValidator(BaseSchemaValidator):
        """
        JSON schema validator according to fast JSON schema.

        `pip install fastjsonschema` to use.

        ```python
        power_supply_output_schema = {
            "type": "object",
            "properties": {
                "current": {"type": "number", "minimum": 0},
                "power": {"type": "number", "minimum": 0, "maximum": 100},
            },
        }
        validator = JSONSchemaValidator(power_supply_output_schema)
        validator.validate({"current": 50, "power": 75})  # valid
        validator.validate({"current": 65, "power": 110})  # raises
        ```
        """

        # Useful for performance with dictionary based schema specification
        # which msgspec has no built in support. Normally, for speed,
        # one should try to use msgspec's struct concept.

        def __init__(self, schema: JSONSchema) -> None:
            super().__init__(schema)
            self.validator = fastjsonschema.compile(schema)

        def validate(self, data) -> None:  # noqa: D102
            self.validator(data)

        def validate_method_call(self, args, kwargs) -> None:  # noqa: D102
            if len(args) > 0:
                kwargs = json_schema_merge_args_to_kwargs(self.schema, args, kwargs)
                # TODO fix type definition
            self.validate(kwargs)

        def json(self) -> JSONSchema:  # noqa: D102
            return self.schema

        def __get_state__(self):
            return self.schema

        def __set_state__(self, schema: JSONSchema):
            return FastJSONSchemaValidator(schema)

except ImportError:
    pass
