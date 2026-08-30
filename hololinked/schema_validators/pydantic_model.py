"""Schema validator based on pydantic models."""

from pydantic import BaseModel

from hololinked.constants import JSONSchemaType
from hololinked.core.interfaces import BaseSchemaValidator
from hololinked.utils import pydantic_validate_args_kwargs


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

    def json(self) -> JSONSchemaType:  # noqa: D102
        return self.schema.model_dump_json()

    def __get_state__(self) -> JSONSchemaType:
        return self.json()

    def __set_state__(self, schema: JSONSchemaType):
        return PydanticSchemaValidator(BaseModel(**schema))
