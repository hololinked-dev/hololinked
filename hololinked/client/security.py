import base64

from pydantic import BaseModel


class BasicSecurity(BaseModel):
    """Basic Security Scheme with username and password"""

    credentials: str

    def __init__(self, username: str, password: str, use_base64: bool = True):
        credentials = f"{username}:{password}"
        if use_base64:
            credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        self._credentials = f"Basic {credentials}"

    @property
    def http_header(self) -> str:
        return self._credentials
