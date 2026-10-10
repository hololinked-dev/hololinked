import pytest

from pydantic import BaseModel

from hololinked.metadata.td.forms import Form
from hololinked.metadata.td.interaction_affordance import (
    PropertyAffordance,
    schema_for_validator,
)
from hololinked.schema_validators.json_schema import JSONSchemaValidator
from hololinked.schema_validators.pydantic_model import PydanticSchemaValidator
from hololinked.utils import issubklass


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "number", "minimum": 0, "maximum": 10, "readOnly": True},
        {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        {"type": "string", "enum": ["a", "b"]},
        {"type": "integer", "const": 5},
    ],
)
def test_01_from_metadata_keeps_schema_keywords(schema):
    form = {"href": "http://localhost:8080/thing/value", "op": "readproperty"}
    td = {"id": "thing", "properties": {"value": {**schema, "forms": [form]}}}
    affordance = PropertyAffordance.from_metadata("value", td)
    assert {key: value for key, value in affordance.json().items() if key != "forms"} == schema
    assert all(isinstance(form, Form) for form in affordance.forms)


@pytest.mark.parametrize(
    "schema_validator, expected",
    [("pydantic", PydanticSchemaValidator), ("json_schema", JSONSchemaValidator)],
)
def test_02_schema_for_validator(schema_validator, expected):
    schema = {"type": "number", "minimum": 0}
    converted, preset = schema_for_validator(schema, "value", schema_validator)
    if expected is PydanticSchemaValidator:
        assert issubklass(converted, BaseModel)
        assert preset is None
    else:
        assert converted is schema
        assert type(preset) is expected


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
