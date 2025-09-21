import typing
from .base import Schema


class SecurityScheme(Schema):
    """
    create security scheme.
    schema - https://www.w3.org/TR/wot-thing-description11/#sec-security-vocabulary-definition
    """

    scheme: str = None
    description: str = None
    descriptions: typing.Optional[typing.Dict[str, str]] = None
    proxy: typing.Optional[str] = None

    def __init__(self):
        super().__init__()

    def build(self):
        self.scheme = "nosec"
        self.description = (
            "currently no security scheme supported - use cookie auth directly on hololinked.server.HTTPServer object"
        )
