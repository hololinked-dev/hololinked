import typing
from pydantic import Field
from .base import Schema
from ..constants import JSON


class ExpectedResponse(Schema):
    """
    Form property.
    schema - https://www.w3.org/TR/wot-thing-description11/#expectedresponse
    """

    contentType: str

    def __init__(self):
        super().__init__()


class AdditionalExpectedResponse(Schema):
    """
    Form field for additional responses which are different from the usual response.
    schema - https://www.w3.org/TR/wot-thing-description11/#additionalexpectedresponse
    """

    success: bool = Field(default=False)
    contentType: str = Field(default="application/json")
    response_schema: typing.Optional[JSON] = Field(default="exception", alias="schema")

    def __init__(self):
        super().__init__()


class Form(Schema):
    """
    Form hypermedia.
    schema - https://www.w3.org/TR/wot-thing-description11/#form
    """

    href: str = None
    op: str = None
    htv_methodName: str = Field(default=None, alias="htv:methodName")
    contentType: typing.Optional[str] = "application/json"
    additionalResponses: typing.Optional[typing.List[AdditionalExpectedResponse]] = None
    contentEncoding: typing.Optional[str] = None
    security: typing.Optional[str] = None
    scopes: typing.Optional[str] = None
    response: typing.Optional[ExpectedResponse] = None
    subprotocol: typing.Optional[str] = None

    def __init__(self):
        super().__init__()

    @classmethod
    def from_TD(cls, form_json: typing.Dict[str, typing.Any]) -> "Form":
        """
        Create a Form instance from a Thing Description JSON object.
        :param form_json: The JSON representation of the form.
        :return: An instance of Form.
        """
        form = cls()
        for field in cls.model_fields:
            if field == "htv_methodName" and "htv:methodName" in form_json:
                setattr(form, field, form_json["htv:methodName"])
            elif field in form_json:
                setattr(form, field, form_json[field])
        return form

    def __str__(self) -> str:
        return f"Form(href={self.href}, op={self.op}, htv_methodName={self.htv_methodName}, contentType={self.contentType})"
