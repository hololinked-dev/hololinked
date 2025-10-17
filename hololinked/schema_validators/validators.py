import jsonschema
from pydantic import BaseModel

from ..utils import pydantic_validate_args_kwargs, json_schema_merge_args_to_kwargs
from ..constants import JSON


class BaseSchemaValidator:  # type definition
    """
    Base class for all schema validators.
    Serves as a type definition.
    """

    def __init__(self, schema: JSON | BaseModel) -> None:
        self.schema = schema

    def validate(self, data) -> None:
        """
        validate the data against the schema.
        """
        raise NotImplementedError("validate method must be implemented by subclass")

    def validate_method_call(self, args, kwargs) -> None:
        """
        validate the method call against the schema.
        """
        raise NotImplementedError("validate_method_call method must be implemented by subclass")


class JSONSchemaValidator(BaseSchemaValidator):
    """
    JSON schema validator according to standard python JSON schema.
    Somewhat slow, consider msgspec if possible.
    """

    def __init__(self, schema) -> None:
        jsonschema.Draft7Validator.check_schema(schema)
        super().__init__(schema)
        self.validator = jsonschema.Draft7Validator(schema)

    def validate(self, data) -> None:
        self.validator.validate(data)

    def validate_method_call(self, args, kwargs) -> None:
        if len(args) > 0:
            kwargs = json_schema_merge_args_to_kwargs(self.schema, args, kwargs)
        self.validate(kwargs)

    def json(self) -> JSON:
        """allows JSON (de-)serializable of the instance itself"""
        return self.schema

    def __get_state__(self):
        return self.schema

    def __set_state__(self, schema):
        return JSONSchemaValidator(schema)


class PydanticSchemaValidator(BaseSchemaValidator):
    """
    JSON schema validator according to pydantic.
    """

    def __init__(self, schema: BaseModel) -> None:
        super().__init__(schema)
        self.validator = schema.model_validate

    def validate(self, data) -> None:
        self.validator(data)

    def validate_method_call(self, args, kwargs) -> None:
        pydantic_validate_args_kwargs(self.schema, args, kwargs)

    def json(self) -> JSON:
        """allows JSON (de-)serializable of the instance itself"""
        return self.schema.model_dump_json()

    def __get_state__(self):
        return self.json()

    def __set_state__(self, schema: JSON):
        return PydanticSchemaValidator(BaseModel(**schema))


try:
    import fastjsonschema

    class FastJsonSchemaValidator(BaseSchemaValidator):
        """
        JSON schema validator according to fast JSON schema.
        Useful for performance with dictionary based schema specification
        which msgspec has no built in support. Normally, for speed,
        one should try to use msgspec's struct concept.
        """

        def __init__(self, schema: JSON) -> None:
            super().__init__(schema)
            self.validator = fastjsonschema.compile(schema)

        def validate(self, data) -> None:
            """validates and raises exception when failed directly to the caller"""
            self.validator(data)

        def validate_method_call(self, args, kwargs) -> None:
            if len(args) > 0:
                kwargs = json_schema_merge_args_to_kwargs(self.schema, args, kwargs)
            self.validate(kwargs)

        def json(self) -> JSON:
            """allows JSON (de-)serializable of the instance itself"""
            return self.schema

        def __get_state__(self):
            return self.schema

        def __set_state__(self, schema):
            return FastJsonSchemaValidator(schema)

except ImportError:
    pass
