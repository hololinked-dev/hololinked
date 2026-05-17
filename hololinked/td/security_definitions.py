"""Implements security scheme definitions for the TD."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from hololinked.td.base import WoTSchema


class SecurityScheme(WoTSchema):
    """
    Subclass from here to implement Security Scheme metadata.

    https://www.w3.org/TR/wot-thing-description11/#sec-security-vocabulary-definition
    """

    scheme: Optional[str] = None
    description: Optional[str] = None
    descriptions: Optional[dict[str, str]] = None
    proxy: Optional[str] = None

    def __init__(self):
        super().__init__()

    def build(self):
        """Populate the security scheme metadata."""
        raise NotImplementedError("Please implement specific security scheme builders")


class NoSecurityScheme(SecurityScheme):
    """No Security Scheme."""

    def build(self):  # noqa: D102
        self.scheme = "nosec"
        self.description = "currently no security scheme supported"


class BasicSecurityScheme(SecurityScheme):
    """Basic Security Scheme - username and password."""

    in_: str = Field(default="header", alias="in")

    def build(self):  # noqa: D102
        self.scheme = "basic"
        self.description = "HTTP Basic Authentication"
        self.in_ = "header"


class APIKeySecurityScheme(SecurityScheme):
    """API Key Security Scheme."""

    in_: str = Field(default="header", alias="in")

    def build(self):  # noqa: D102
        self.scheme = "apikey"
        self.description = "API Key Authentication"
        self.in_ = "header"


class OIDCSecurityScheme(SecurityScheme):
    """OIDC Security Scheme."""

    scheme: str = "oauth2"
    token: str = ""
    scopes: list[str] = Field(default_factory=list)

    def build(  # noqa: D102
        self,
        token_url: str,
        scopes: list[str] | None = ["openid"],
    ) -> None:  # ty: ignore[invalid-method-override]
        self.description = "OpenID Connect Authentication"
        self.token = token_url
        if scopes is not None:
            self.scopes = scopes
