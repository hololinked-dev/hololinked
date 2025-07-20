import typing 
from pydantic import Field
from .base import Schema 
from ..constants import JSON



class ExpectedResponse(Schema):
    """
    Form property. 
    schema - https://www.w3.org/TR/wot-thing-description11/#expectedresponse
    """
    contentType : str

    def __init__(self):
        super().__init__()


class AdditionalExpectedResponse(Schema):
    """
    Form field for additional responses which are different from the usual response.
    schema - https://www.w3.org/TR/wot-thing-description11/#additionalexpectedresponse
    """
    success: bool = Field(default=False)
    contentType: str = Field(default='application/json')
    response_schema: typing.Optional[JSON] = Field(default='exception', alias='schema')

    def __init__(self):
        super().__init__()


class Form(Schema):
    """
    Form hypermedia.
    schema - https://www.w3.org/TR/wot-thing-description11/#form
    """
    href: str = None
    op: str = None 
    htv_methodName: str = Field(default=None, alias='htv:methodName') 
    contentType: typing.Optional[str] = None
    additionalResponses: typing.Optional[typing.List[AdditionalExpectedResponse]] = None
    contentEncoding: typing.Optional[str] = None
    security: typing.Optional[str] = None
    scopes: typing.Optional[str] = None
    response: typing.Optional[ExpectedResponse] = None
    subprotocol: typing.Optional[str] = None
    
    def __init__(self):
        super().__init__()