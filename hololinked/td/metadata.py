import typing 
from dataclasses import dataclass, field
from .base import Schema


@dataclass
class Link(Schema):
    href : str
    anchor : typing.Optional[str]  
    type : typing.Optional[str] = field(default='application/json')
    # rel : typing.Optional[str] = field(default='next')

    def __init__(self):
        super().__init__()
    
    def build(self, resource, owner, authority : str) -> None:
        self.href = f"{authority}{resource._full_URL_path_prefix}/resources/wot-td"
        self.anchor = f"{authority}{owner._full_URL_path_prefix}"


@dataclass
class VersionInfo:
    """
    create version info.
    schema - https://www.w3.org/TR/wot-thing-description11/#versioninfo
    """
    instance : str 
    model : str