import jsonschema
import pytest

from hololinked.core.interfaces.schema_validators import BaseSchemaValidator
from hololinked.metadata.td.pydantic_extensions import dataschema_to_model
from hololinked.schema_validators.fast_json_schema import FastJSONSchemaValidator
from hololinked.schema_validators.json_schema import JSONSchemaValidator
from hololinked.schema_validators.pydantic_model import PydanticSchemaValidator


NUMBER = {"type": "number", "minimum": 0}
ONE_OF = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
DICTIONARY = {"type": "object", "additionalProperties": {"type": "integer"}}
OBJECT = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}

each_validator = pytest.mark.parametrize(
    "make_validator",
    [
        lambda schema: PydanticSchemaValidator(dataschema_to_model(schema, "action_input")),
        JSONSchemaValidator,
        FastJSONSchemaValidator,
    ],
    ids=["pydantic", "json_schema", "fastjsonschema"],
)


def test_method_call(validator: BaseSchemaValidator, args: tuple, kwargs: dict, valid: bool) -> None:
    if valid:
        validator.validate_method_call(args, kwargs)
    else:
        with pytest.raises((ValueError, jsonschema.ValidationError)):
            validator.validate_method_call(args, kwargs)


@each_validator
@pytest.mark.parametrize(
    "schema, args, kwargs, valid",
    [
        (NUMBER, (5,), {}, True),
        (NUMBER, (), {"value": 5}, True),
        (NUMBER, (-1,), {}, False),
        (NUMBER, (1, 2), {}, False),
        (NUMBER, (), {}, False),
        (ONE_OF, ("x",), {}, True),
        (ONE_OF, (1.5,), {}, False),
    ],
)
def test_01_single_value_input(make_validator, schema, args, kwargs, valid):
    """an input that is not an object is one value, given positionally or as the only keyword argument."""
    test_method_call(make_validator(schema), args, kwargs, valid)


@each_validator
@pytest.mark.parametrize(
    "args, kwargs, valid",
    [
        ((), {"a": 1, "b": 2}, True),
        ((), {"a": "x"}, False),
        (({"a": 1},), {}, False),
    ],
)
def test_02_mapping_input(make_validator, args, kwargs, valid):
    """an object without properties needs all arguments as keywords."""
    test_method_call(make_validator(DICTIONARY), args, kwargs, valid)


@each_validator
@pytest.mark.parametrize(
    "args, kwargs, valid",
    [
        ((1,), {}, True),
        ((), {"a": 1}, True),
        ((), {"a": "x"}, False),
    ],
)
def test_03_fields_input(make_validator, args, kwargs, valid):
    """an object with properties maps the arguments onto them."""
    test_method_call(make_validator(OBJECT), args, kwargs, valid)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
