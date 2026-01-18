import base64
import threading
import time

import httpx

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


class ROPC(BaseModel):
    access_token: str
    id_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    scope: str


class OAuthDirectAccessGrant(BaseModel):
    """
    OAuth2 Direct Access Grant Security Scheme.
    Implements Resource Owner Password Credentials (ROPC) flow.
    """

    oidc_server_url: str
    oidc_realm: str
    oidc_client_id: str
    oidc_client_secret: str | None = None
    username: str
    password: str
    scope: str | list[str] = "openid"
    grant_type: str = "password"

    @property
    def oidc_provider_url(self) -> str:
        return f"{self.oidc_server_url}/realms/{self.oidc_realm}"


class OAuth2Security:
    """
    OAuth2 Security Scheme,
    currently only supports Resource Owner Password Credentials (ROPC) flow.
    """

    http_header_name: str = "Authorization"

    def __init__(
        self,
        oidc_settings: OAuthDirectAccessGrant,
        req_rep_sync_client: httpx.Client,
        req_rep_async_client: httpx.AsyncClient,
        refresh_interval_fraction: float = 0.75,
    ) -> None:
        self._oidc_settings = oidc_settings
        self._req_rep_async_client = req_rep_async_client
        self._req_rep_sync_client = req_rep_sync_client
        self._tokens = None
        self._refresh_thread = None
        self._refresh_lock = threading.Lock()
        self._refresh = True
        self._refresh_interval_fraction = refresh_interval_fraction

    @property
    def http_header(self) -> str:
        if not self._tokens:
            return ""
        try:
            self._refresh_lock.acquire()
            return f"Bearer {self._tokens.access_token}"
        finally:
            self._refresh_lock.release()

    def login(self) -> None:
        """login with username and password and obtain tokens"""
        try:
            self._refresh_lock.acquire()
            body = dict(
                grant_type=self._oidc_settings.grant_type,
                client_id=self._oidc_settings.oidc_client_id,
                scope=self._oidc_settings.scope,
                username=self._oidc_settings.username,
                password=self._oidc_settings.password,
            )
            if self._oidc_settings.oidc_client_secret:
                body["client_secret"] = self._oidc_settings.oidc_client_secret
            response = self._req_rep_sync_client.post(
                f"{self._oidc_settings.oidc_provider_url}/protocol/openid-connect/token",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            self._tokens = ROPC(**response.json())
            if self._refresh_thread and self._refresh_thread.is_alive():
                return
            self._refresh_thread = threading.Thread(target=self._refresh_tokens_in_background, daemon=True)
            self._refresh_thread.start()
        finally:
            self._refresh_lock.release()

    def logout(self) -> None:
        """logout and invalidate tokens"""
        body = dict(
            client_id=self._oidc_settings.oidc_client_id,
            refresh_token=self._tokens.refresh_token,
        )
        if self._oidc_settings.oidc_client_secret:
            body["client_secret"] = self._oidc_settings.oidc_client_secret
        response = self._req_rep_sync_client.post(
            f"{self._oidc_settings.oidc_provider_url}/protocol/openid-connect/logout",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        self._tokens = None
        self._refresh = False

    def refresh_tokens(self) -> None:
        """refresh tokens, even forcibly by relogin if necessary"""
        try:
            self._refresh_lock.acquire()
            body = dict(
                grant_type="refresh_token",
                client_id=self._oidc_settings.oidc_client_id,
                refresh_token=self._tokens.refresh_token,
            )
            if self._oidc_settings.oidc_client_secret:
                body["client_secret"] = self._oidc_settings.oidc_client_secret
            response = self._req_rep_sync_client.post(
                f"{self._oidc_settings.oidc_provider_url}/protocol/openid-connect/token",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            self._tokens = ROPC(**response.json())
        except httpx.HTTPStatusError:
            self._refresh_lock.release()
            self.login()
        finally:
            self._refresh_lock.release()

    def _refresh_tokens_in_background(self) -> None:
        """background thread to refresh tokens periodically"""
        time.sleep(int(0.75 * self._tokens.expires_in))
        while self._refresh:
            self.refresh_tokens()
            time.sleep(int(self._refresh_interval_fraction * self._tokens.expires_in))
