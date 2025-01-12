import typing 
from dataclasses import dataclass, field
from .base import Schema, JSON


@dataclass
class ExpectedResponse(Schema):
    """
    Form property. 
    schema - https://www.w3.org/TR/wot-thing-description11/#expectedresponse
    """
    contentType : str

    def __init__(self):
        super().__init__()


@dataclass
class AdditionalExpectedResponse(Schema):
    """
    Form field for additional responses which are different from the usual response.
    schema - https://www.w3.org/TR/wot-thing-description11/#additionalexpectedresponse
    """
    success : bool = field(default=False)
    contentType : str = field(default='application/json')
    schema : typing.Optional[JSON] = field(default='exception')

    def __init__(self):
        super().__init__()


@dataclass
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