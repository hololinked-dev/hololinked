import base64
import threading
import time
import warnings

import httpx

from pydantic import BaseModel, PrivateAttr


class BasicSecurity(BaseModel):
    """
    Basic Security Scheme with username and password. The credentials are added into the `Authorization` header.
    Normally, you can instantiate this indirectly through the `ClientFactory` by passing `username` and `password`
    parameters, if the protocol supports it.

    ```python
    client = ClientFactory.http(
        url="http://localhost:9000/my-thing/resources/wot-td",
        security=BasicSecurity(
            username=os.getenv("USERNAME", "admin"),
            password=os.getenv("PASSWORD", "adminpass"),
            base64_encoding=True
        )
    )
    ```
    """

    http_header_name: str = "Authorization"
    """
    Name of the HTTP header to use for authentication, default is `Authorization`.
    Override this if the server expects the credentials in a different header.
    """

    _credentials: str = PrivateAttr()

    def __init__(self, username: str, password: str, use_base64: bool = True) -> None:
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
        """Value for the Authorization header - contains the credentials"""
        return self._credentials


class APIKeySecurity(BaseModel):
    """
    API Key Security Scheme. The API key is added into a header named `X-API-Key`.

    ```python
    client = ClientFactory.http(
        url="http://localhost:9000/my-thing/resources/wot-td",
        security_scheme=APIKeySecurity(value=os.getenv("APIKEY", "default-api-key"))
    )
    ```
    """

    value: str
    """The API key value to use for authentication."""

    http_header_name: str = "X-API-Key"
    """
    Name of the HTTP header to use for authentication, default is `X-API-Key`.
    Override this if the server expects the API key in a different header.
    """

    @property
    def http_header(self) -> str:
        return self.value


class ROPC(BaseModel):
    access_token: str
    scope: str
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str | None = None
    id_token: str | None = None


class OAuthDirectAccessGrant(BaseModel):
    """
    OAuth2 Direct Access Grant Security Scheme. Implements Resource Owner Password Credentials (ROPC) flow - in simple
    terms, plain username and password authentication without the general features of OAuth2. Please implement other
    flows on your own for applications with a web interface. There is no intention to provide a complete OAuth2 client
    implementation in this library.
    """

    token_endpoint: str
    client_id: str
    client_secret: str | None = None
    revocation_endpoint: str | None = None

    username: str
    password: str
    scope: str | list[str] = "openid"
    grant_type: str = "password"

    def __init__(
        self,
        username: str,
        password: str,
        oidc_config_url: str | None = None,
        token_endpoint: str | None = None,
        scope: str | list[str] = "openid",
        verify_ssl: bool = True,
        **kwargs,
    ):
        """
        Initialize OAuthDirectAccessGrant security scheme.

        Parameters
        ----------
        username: str
            The username for authentication.
        password: str
            The password for authentication.
        oidc_config_url: str | None
            The URL to fetch OIDC configuration, which should contain the token endpoint and optionally the
            revocation endpoint. If provided, `token_endpoint` (next argument) will be ignored.
        token_endpoint: str | None
            The token endpoint URL for obtaining tokens. Required if `oidc_config_url` is not provided.
        scope: str | list[str]
            The scope to request when obtaining tokens, by default "openid".
        verify_ssl: bool
            Whether to verify SSL certificates when fetching OIDC configuration, by default True.
            Set to False if you are using self-signed certificates in development or testing environments or using
            a local provider.
        kwargs:
            client_id: str
                The client ID for authentication, required for most OIDC providers.
            client_secret: str
                The client secret for authentication, required for some OIDC providers.
            revocation_endpoint: str
                The token revocation endpoint URL, required if you want to support logout functionality.
                If not provided, logout functionality will not be available.
        """
        client_id = kwargs.get("client_id", None)
        client_secret = kwargs.get("client_secret", None)
        revocation_endpoint = kwargs.get("revocation_endpoint", None)
        if oidc_config_url:
            with httpx.Client(timeout=10.0, verify=verify_ssl) as client:
                response = client.get(oidc_config_url)
                response.raise_for_status()
                oidc_config = response.json()
                token_endpoint = oidc_config["token_endpoint"]
                revocation_endpoint = oidc_config.get("revocation_endpoint", None)
        elif not token_endpoint:
            raise ValueError("Either 'oidc_config_url' or 'token_endpoint' must be provided")
        super().__init__(
            token_endpoint=token_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            revocation_endpoint=revocation_endpoint,
            username=username,
            password=password,
            scope=scope,
        )


class OAuth2Security:
    """
    OAuth2 Security Scheme, supporting only direct access grant or Resource Owner Password Credentials (ROPC) flow.
    Please implement other flows on your own for applications with a web interface.
    """

    http_header_name: str = "Authorization"

    def __init__(
        self,
        oidc_settings: OAuthDirectAccessGrant,
        refresh_interval_fraction: int | float = 0.75,
        **kwargs,
    ) -> None:
        """
        Initialize OIDC security scheme.

        Parameters
        ----------
        oidc_settings: OAuthDirectAccessGrant
            The settings for OIDC authentication, including token endpoint, client id, username and password.
        refresh_interval_fraction: int | float
            The fraction of token expiration time to wait before refreshing tokens, by default 0.75,
            which means refreshing tokens when 75% of the token expiration time has passed.
        kwargs:
            sync_http_client: httpx.Client
                The http client to use for synchronous requests, by default a new httpx.Client with 10s timeout.
            async_http_client: httpx.AsyncClient
                The http client to use for asynchronous requests, by default a new httpx.AsyncClient with 10s timeout.
                Unused currently, optional.
        """
        self.oidc_settings = oidc_settings
        self.tokens = None
        self._sync_http_client = kwargs.get("sync_http_client", httpx.Client(timeout=10.0))  # type: httpx.Client
        self._async_http_client = kwargs.get("async_http_client", httpx.AsyncClient(timeout=10.0))  # type: httpx.AsyncClient
        self._refresh_thread = None
        self._refresh = True
        self._refresh_interval_fraction = refresh_interval_fraction

    @property
    def http_header(self) -> str:
        if not self.tokens:
            return ""
        return f"Bearer {self.tokens.access_token}"

    def login(self) -> None:
        """login with username and password and obtain tokens"""
        body = dict(
            grant_type=self.oidc_settings.grant_type,
            client_id=self.oidc_settings.client_id,
            scope=self.oidc_settings.scope,
            username=self.oidc_settings.username,
            password=self.oidc_settings.password,
        )
        if self.oidc_settings.client_secret:
            body["client_secret"] = self.oidc_settings.client_secret
        response = self._sync_http_client.post(
            self.oidc_settings.token_endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        self.tokens = ROPC(
            access_token=response.json().get("access_token"),
            refresh_token=response.json().get("refresh_token"),
            expires_in=response.json().get("expires_in"),
            id_token=response.json().get("id_token"),
            scope=response.json().get("scope"),
            token_type=response.json().get("token_type"),
        )
        if self._refresh_thread and self._refresh_thread.is_alive():
            return
        self._refresh_thread = threading.Thread(target=self._refresh_tokens_in_background, daemon=True)
        self._refresh_thread.start()

    def logout(self) -> None:
        """logout and invalidate tokens"""
        if not self.tokens or not self.oidc_settings.revocation_endpoint:
            return
        body = dict(
            client_id=self.oidc_settings.client_id,
            token=self.tokens.refresh_token if self.tokens.refresh_token else self.tokens.access_token,
            token_type_hint="refresh_token" if self.tokens.refresh_token else "access_token",
        )
        if self.oidc_settings.client_secret:
            body["client_secret"] = self.oidc_settings.client_secret
        response = self._sync_http_client.post(
            self.oidc_settings.revocation_endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        self.tokens = None
        self._refresh = False

    def refresh_tokens(self) -> None:
        """refresh tokens, even forcibly by relogin if necessary"""
        if not self.tokens:
            return
        if not self.tokens.refresh_token:
            warnings.warn(
                "OIDC refresh token not available, cannot refresh tokens."
                + "You need to login again to obtain new tokens.",
                UserWarning,
            )
            return
        try:
            body = dict(
                grant_type="refresh_token",
                client_id=self.oidc_settings.client_id,
                refresh_token=self.tokens.refresh_token,
            )
            if self.oidc_settings.client_secret:
                body["client_secret"] = self.oidc_settings.client_secret
            response = self._sync_http_client.post(
                self.oidc_settings.token_endpoint,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            self.tokens = ROPC(
                access_token=response.json().get("access_token"),
                refresh_token=response.json().get("refresh_token"),
                expires_in=response.json().get("expires_in", self.tokens.expires_in),
                id_token=response.json().get("id_token", self.tokens.id_token),
                scope=response.json().get("scope", self.tokens.scope),
                token_type=response.json().get("token_type", self.tokens.token_type),
            )
        except httpx.HTTPStatusError:
            self.login()

    def _refresh_tokens_in_background(self) -> None:
        """background thread to refresh tokens periodically"""
        if not self.tokens:
            return
        if not self.tokens.expires_in:
            warnings.warn(
                "OIDC token expiration time is not set. Automatic token refresh will not work."
                + "You need to manually login again once access token is expired.",
                UserWarning,
            )
            return
        while self._refresh:
            time.sleep(int(self._refresh_interval_fraction * self.tokens.expires_in))
            self.refresh_tokens()
