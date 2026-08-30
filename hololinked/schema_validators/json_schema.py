"""JSON schema validator based on the standard python `jsonschema` package."""

import jsonschema

from hololinked.constants import JSONSchemaType
from hololinked.core.interfaces import BaseSchemaValidator
from hololinked.utils import json_schema_merge_args_to_kwargs


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

    def __init__(self, schema: JSONSchemaType) -> None:
        """
        Initialize the validator.

        Parameters
        ----------
        schema: JSONSchemaType
            The JSON schema to validate against
        """
        self.check_schema(schema)
        super().__init__(schema)
        self.validator = jsonschema.Draft7Validator(schema)

    @classmethod
    def check_schema(cls, schema: JSONSchemaType) -> None:
        """
        Check that the given object is itself a valid JSON schema.

        Parameters
        ----------
        schema: JSONSchemaType
            the schema to check

        Raises
        ------
        jsonschema.SchemaError
            if the schema is not a valid JSON schema
        """
        jsonschema.Draft7Validator.check_schema(schema)

    def validate(self, data) -> None:  # noqa: D102
        self.validator.validate(data)

    def validate_method_call(self, args, kwargs) -> None:  # noqa: D102
        if len(args) > 0:
            kwargs = json_schema_merge_args_to_kwargs(self.schema, args, kwargs)
            # TODO fix type definition
        self.validate(kwargs)

    def json(self) -> JSONSchemaType:  # noqa: D102
        return self.schema

    def __get_state__(self) -> JSONSchemaType:
        return self.schema

    def __set_state__(self, schema: JSONSchemaType):
        return JSONSchemaValidator(schema)
