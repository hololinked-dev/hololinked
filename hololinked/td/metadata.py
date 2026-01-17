from typing import Optional

from pydantic import Field

from .base import Schema


class Link(Schema):
    """
    Represents a link in the link section of the TD
    schema - https://www.w3.org/TR/wot-thing-description11/#link
    """

    href: str
    anchor: Optional[str]
    rel: Optional[str]
    type: Optional[str] = Field(default="application/json")


class VersionInfo(Schema):
    """
    Represents version info.
    schema - https://www.w3.org/TR/wot-thing-description11/#versioninfo
    """

    instance: str
    model: str
