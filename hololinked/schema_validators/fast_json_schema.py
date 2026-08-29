"""JSON schema validator based on the `fastjsonschema` package. `pip install fastjsonschema` to use."""

import fastjsonschema
import jsonschema

from hololinked.constants import JSONSchemaType
from hololinked.core.interfaces import BaseSchemaValidator
from hololinked.utils import json_schema_merge_args_to_kwargs


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
    validator = FastJSONSchemaValidator(power_supply_output_schema)
    validator.validate({"current": 50, "power": 75})  # valid
    validator.validate({"current": 65, "power": 110})  # raises
    ```

    Useful for performance with dictionary based schema specification, which msgspec has no built in support for.
    Normally, for speed, one should try to use msgspec's struct concept.
    """

    def __init__(self, schema: JSONSchemaType) -> None:
        """
        Initialize the validator.

        Parameters
        ----------
        schema: JSONSchemaType
            The JSON schema to validate against
        """
        super().__init__(schema)
        self.validator = fastjsonschema.compile(schema)

    @classmethod
    def check_schema(cls, schema: JSONSchemaType) -> None:
        """
        Check that the given object is itself a valid JSON schema.

        `fastjsonschema` has no schema checker of its own, therefore the standard `jsonschema` package is used.

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
        self.validator(data)

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
        return FastJSONSchemaValidator(schema)
