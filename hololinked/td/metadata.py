"""Include a general metadata like links, version info, etc. here."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from hololinked.td.base import WoTSchema


class Link(WoTSchema):
    """
    Impelements the Link schema for linking to other resources.

    https://www.w3.org/TR/wot-thing-description11/#link
    """

    href: str
    anchor: Optional[str]
    rel: Optional[str]
    type: Optional[str] = Field(default="application/json")


class VersionInfo(WoTSchema):
    """
    Represents version info.

    https://www.w3.org/TR/wot-thing-description11/#versioninfo
    """

    instance: str
    model: str
