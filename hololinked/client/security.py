import base64

from pydantic import BaseModel, PrivateAttr


class BasicSecurity(BaseModel):
    """
    Basic Security Scheme with username and password.
    The credentials are added into the `Authorization` header.
    """

    http_header_name: str = "Authorization"

    _credentials: str = PrivateAttr()

    def __init__(self, username: str, password: str, use_base64: bool = True):
        """
        Parameters
        ----------
        username: str
            The username for basic authentication
        password: str
            The password for basic authentication
        use_base64: bool
            Whether to encode the credentials in base64, by default True
        """
        super().__init__()
        credentials = f"{username}:{password}"
        if use_base64:
            credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        self._credentials = f"Basic {credentials}"

    @property
    def http_header(self) -> str:
        """Value for the Authorization header"""
        return self._credentials


class APIKeySecurity(BaseModel):
    """
    API Key Security Scheme.
    The API key is added into a header named `X-API-Key`.
    """

    value: str
    http_header_name: str = "X-API-Key"

    @property
    def http_header(self) -> str:
        return self.value
