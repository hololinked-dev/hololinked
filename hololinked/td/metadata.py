from typing import Optional

from pydantic import Field

from .base import Schema


class Link(Schema):
    href: str
    anchor: Optional[str]
    rel: Optional[str]
    type: Optional[str] = Field(default="application/json")


class VersionInfo(Schema):
    """
    create version info.
    schema - https://www.w3.org/TR/wot-thing-description11/#versioninfo
    """

    instance: str
    model: str
