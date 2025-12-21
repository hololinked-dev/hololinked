import base64

from pydantic import BaseModel, PrivateAttr


class BasicSecurity(BaseModel):
    """Basic Security Scheme with username and password"""

    http_header_name: str = "Authorization"

    _credentials: str = PrivateAttr()

    def __init__(self, username: str, password: str, use_base64: bool = True):
        super().__init__()
        credentials = f"{username}:{password}"
        if use_base64:
            credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        self._credentials = f"Basic {credentials}"

    @property
    def http_header(self) -> str:
        return self._credentials


class APIKeySecurity(BaseModel):
    """API Key Security Scheme"""

    apikey: str
    http_header_name: str = "X-API-Key"

    @property
    def http_header(self) -> str:
        return self.apikey
