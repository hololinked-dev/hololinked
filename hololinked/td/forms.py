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
    href : str 
    op : str 
    htv_methodName : str 
    contentType : typing.Optional[str]
    additionalResponses : typing.Optional[typing.List[AdditionalExpectedResponse]]
    contentEncoding : typing.Optional[str]
    security : typing.Optional[str]
    scopes : typing.Optional[str]
    response : typing.Optional[ExpectedResponse]
    subprotocol : typing.Optional[str]
    
    def __init__(self):
        super().__init__()