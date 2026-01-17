from typing import Optional

from pydantic import Field

from .base import Schema


class SecurityScheme(Schema):
    """
    Represents a security scheme.
    schema - https://www.w3.org/TR/wot-thing-description11/#sec-security-vocabulary-definition
    """

    scheme: str = None
    description: str = None
    descriptions: Optional[dict[str, str]] = None
    proxy: Optional[str] = None

    def __init__(self):
        super().__init__()

    def build(self):
        raise NotImplementedError("Please implement specific security scheme builders")


class NoSecurityScheme(SecurityScheme):
    """No Security Scheme"""

    def build(self):
        self.scheme = "nosec"
        self.description = "currently no security scheme supported"


class BasicSecurityScheme(SecurityScheme):
    """Basic Security Scheme, username and password"""

    in_: str = Field(default="header", alias="in")

    def build(self):
        self.scheme = "basic"
        self.description = "HTTP Basic Authentication"
        self.in_ = "header"


class APIKeySecurityScheme(SecurityScheme):
    """API Key Security Scheme"""

    in_: str = Field(default="header", alias="in")

    def build(self):
        self.scheme = "apikey"
        self.description = "API Key Authentication"
        self.in_ = "header"
