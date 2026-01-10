from typing import Any, Optional

from pydantic import Field

from ..constants import JSON
from .base import Schema


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
    response_schema: Optional[JSON] = Field(default="exception", alias="schema")

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
    mqv_topic: str = Field(default=None, alias="mqv:topic")
    contentType: Optional[str] = "application/json"
    additionalResponses: Optional[list[AdditionalExpectedResponse]] = None
    contentEncoding: Optional[str] = None
    security: Optional[str] = None
    scopes: Optional[str] = None
    response: Optional[ExpectedResponse] = None
    subprotocol: Optional[str] = None

    def __init__(self):
        super().__init__()

    @classmethod
    def from_TD(cls, form_json: dict[str, Any]) -> "Form":
        """
        Create a Form instance from a Thing Description JSON object.

        Parameters
        ----------
        form_json: dict[str, Any]
            The JSON representation of the form.

        Returns
        -------
        Form
            An instance of Form.
        """
        form = cls()
        for field in cls.model_fields:
            if field == "htv_methodName" and "htv:methodName" in form_json:
                setattr(form, field, form_json["htv:methodName"])
            elif field == "mqv_topic" and "mqv:topic" in form_json:
                setattr(form, field, form_json["mqv:topic"])
            elif field in form_json:
                setattr(form, field, form_json[field])
        return form

    def __str__(self) -> str:
        return f"Form(href={self.href}, op={self.op}, htv_methodName={self.htv_methodName}, contentType={self.contentType})"
