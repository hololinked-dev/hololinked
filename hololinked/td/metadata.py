"""Include a general metadata like links, version info, etc. here."""

from typing import Optional

from pydantic import Field

from .base import Schema


class Link(Schema):
    """
    Impelements the Link schema for linking to other resources.

    https://www.w3.org/TR/wot-thing-description11/#link
    """

    href: str
    anchor: Optional[str]
    rel: Optional[str]
    type: Optional[str] = Field(default="application/json")


class VersionInfo(Schema):
    """
    Represents version info.

    https://www.w3.org/TR/wot-thing-description11/#versioninfo
    """

    instance: str
    model: str
