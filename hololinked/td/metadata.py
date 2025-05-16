import typing
from pydantic import Field 

from .base import Schema



class Link(Schema):
    href : str
    anchor: typing.Optional[str]  
    rel: typing.Optional[str] 
    type: typing.Optional[str] = Field(default='application/json')

    def __init__(self):
        super().__init__()
    
    def build(self, resource, owner, authority : str) -> None:
        self.href = f"{authority}{resource._full_URL_path_prefix}/resources/wot-td"
        self.anchor = f"{authority}{owner._full_URL_path_prefix}"



class VersionInfo(Schema):
    """
    create version info.
    schema - https://www.w3.org/TR/wot-thing-description11/#versioninfo
    """
    instance : str 
    model : str