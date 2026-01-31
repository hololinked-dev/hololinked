"""Implementation of security schemes for a server"""

import base64
import json
import os
import secrets
import string

from datetime import datetime, timedelta
from typing import Any

import httpx

from pydantic import BaseModel, PrivateAttr, field_serializer, field_validator

from ..config import global_config
from ..utils import uuid_hex


class Security(BaseModel):
    """Type definition for security schemes"""

    pass


try:
    import bcrypt

    class BcryptBasicSecurity(Security):
        """
        A username and password based security scheme using bcrypt.
        The password is stored as a hash.

        The request must supply an authorization header in of the following formats:

        - `Authorization: Basic base64(username:password)`
        - `Authorization: Basic (username:password)`

        The username and password are expected to be base64 encoded, by default.
        Set `expect_base64=False` if you want to use plain text credentials without base64 encoding.

        Use bcrypt when you are constrained in terms of memory. Use Argon2BasicSecurity
        when you can afford more memory (which is the recommended username-password implementation).

        Note: bcrypt is a cpu-hard hashing algorithm, which means it is resistant to brute-force attacks.
        """

        username: str
        expect_base64: bool
        name: str

        _password_hash: bytes = PrivateAttr()

        def __init__(self, username: str, password: str, expect_base64: bool = True, name: str = "") -> None:
            """
            Parameters
            ----------
            username: str
                The username to be used for authentication
            password: str
                The password to be used for authentication
            expect_base64: bool
                Whether to expect base64 encoded credentials in the authorization header. Default is True.
            name: str
                An optional unique name for the security scheme that will be used in TD security definitions.
            """
            super().__init__(
                username=username,
                expect_base64=expect_base64,
                name=name or f"bcrypt-basic-{uuid_hex()}",
            )
            self._password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

        def validate_input(self, username: str, password: str) -> bool:
            """
            plain validate a username and password

            Returns
            -------
            bool
                True if the username and password are valid, False otherwise
            """
            if username != self.username:
                return False
            return bcrypt.checkpw(password.encode("utf-8"), self._password_hash)

        def validate_base64(self, b64_str: str) -> bool:
            """
            Validate a base64 encoded string containing username and password.
            Please strip the 'Basic ' prefix before passing as argument.

            Returns
            -------
            bool
                True if the username and password are valid, False otherwise
            """
            if not self.expect_base64:
                raise ValueError("base64 encoded credentials not expected, please reconfigure if needed")
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8")
            except (ValueError, TypeError):
                return False
            username, password = decoded.split(":", 1)
            return self.validate_input(username, password)

except ImportError:

    class BcryptBasicSecurity(Security):
        """
        Placeholder for BcryptBasicSecurity when bcrypt is not installed.
        Please install the `bcrypt` library to use Bcrypt password security and see the actual docstrings.
        """

        def __init__(self, username: str, password: str, expect_base64: bool = True, name: str = "") -> None:
            raise ImportError("bcrypt library is required for BcryptBasicSecurity")


try:
    import argon2

    class Argon2BasicSecurity(Security):
        """
        A username and password based security scheme using Argon2.
        The password is stored as a hash.

        The request must supply an authorization header in of the following formats:

        - `Authorization: Basic base64(username:password)`
        - `Authorization: Basic (username:password)`

        The username and password are expected to be base64 encoded, by default.
        Set `expect_base64=False` if you want to use plain text credentials without base64 encoding.

        Argon2 is the recommended password hashing security scheme.
        """

        username: str
        expect_base64: bool
        name: str

        _password_hash: str = PrivateAttr()
        _ph: argon2.PasswordHasher | None = PrivateAttr(default=None)

        def __init__(self, username: str, password: str, expect_base64: bool = True, name: str = "") -> None:
            """
            Parameters
            ----------
            username: str
                username
            password: str
                password
            expect_base64: bool
                Whether to expect base64 encoded credentials in the authorization header. Default is True.
            name: str
                An optional unique name for the security scheme that will be used in TD security definitions.
            """
            super().__init__(
                username=username,
                expect_base64=expect_base64,
                name=name or f"argon2-basic-{uuid_hex()}",
            )
            self._ph = argon2.PasswordHasher()
            self._password_hash = self._ph.hash(password)

        def validate_input(self, username: str, password: str) -> bool:
            """
            plain validate a username and password

            Returns
            -------
            bool
                True if the username and password are valid, False otherwise
            """
            if username != self.username:
                return False
            try:
                return self._ph.verify(self._password_hash, password)
            except argon2.exceptions.VerifyMismatchError:
                return False

        def validate_base64(self, b64_str: str) -> bool:
            """
            Validate a base64 encoded string containing username and password.
            Please strip the 'Basic ' prefix before passing.

            Returns
            -------
            bool
                True if the username and password are valid, False otherwise
            """
            if not self.expect_base64:
                raise ValueError("base64 encoded credentials not expected, please reconfigure if needed")
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8")
            except (ValueError, TypeError):
                return False
            username, password = decoded.split(":", 1)
            return self.validate_input(username, password)

except ImportError:

    class Argon2BasicSecurity(Security):
        """
        Placeholder for Argon2BasicSecurity when argon2 is not installed.
        Please install the `argon2-cffi` library to use Argon2 password security.
        """

        def __init__(self, username: str, password: str, expect_base64: bool = True, name: str = "") -> None:
            raise ImportError("argon2-cffi library is required for Argon2BasicSecurity")


try:
    import argon2

    class APIKeyRecord(BaseModel):
        """An API key record dataclass"""

        name: str
        id: str
        apikey_hash: str
        description: str
        created_at: datetime
        expiry_at: datetime
        hasher: str = "argon2"

        @field_serializer("created_at", "expiry_at")
        def serialize_datetime(self, dt: datetime, _info) -> str:
            """Serialize datetime to ISO format string"""
            return dt.isoformat()

        @field_validator("created_at", "expiry_at", mode="before")
        @classmethod
        def parse_datetime(cls, value):
            """Parse datetime from string or return datetime object"""
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            return value

    class APIKeySecurity(Security):
        """
        An API key based security scheme.

        Use API keys in place of username-password combinations when there is a requirement to keep track of different
        clients and expire their keys after a definite period. More features will be added in future.

        Before your application uses the API key, you need to create and store an API key using the `create()` method,
        otherwise a `ValueError` will be raised when validating. This creation of API key may be outside the
        scope of your application code.

        Once created, instantiate this class once again with the name and pass it to your server
        (currently only HTTP server).

        Secrets are stored under the `global_config.TEMP_DIR` under a `secrets` directory in a JSON file.

        The request must supply an authorization header in the format: `X-API-Key: <value>`
        """

        name: str
        file: str
        record: APIKeyRecord | None = None

        _ph: argon2.PasswordHasher = PrivateAttr()

        def __init__(self, name: str, file: str = "apikeys.json", hasher: Any = None) -> None:
            """
            Parameters
            ----------
            name: str
                The unique name for the security scheme found in the storage file & in TD security definitions
            file: str
                The file to load/store the API keys, defaults to 'apikeys.json' in the default secrets directory.
                You need to overload both `global_config.TEMP_DIR` and this filename to use a different location.
            """
            super().__init__(name=name, file=os.path.join(global_config.TEMP_DIR_SECRETS, file))
            self._ph = hasher or argon2.PasswordHasher()
            self.record = None
            self.load()

        def create(
            self,
            size: int = 24,
            id_size: int = 5,
            validity_period_minutes: int = 30 * 24 * 60,
            description: str = "API Key for WoT applications",
            file: str = "apikeys.json",
            allowed_characters: str = string.ascii_letters + string.digits + "_",
            prefix: str = "wotdat",
            print_value: bool = True,
            override: bool = False,
        ) -> str:
            """
            Create a new API key. Use this method to generate and store a new API key before running your application.
            The validity period, specified in minutes (default 30 days), is stored as validation metadata and not a part
            of the key itself. Nevertheless, this is checked during validation.

            The format of the key is `<prefix>-<id>.<secret>`, where both id and secret are randomly generated strings.

            Parameters
            ----------
            size: int
                The size of the secret part of the API key, defaults to 24 characters
            id_size: int
                The size of the ID part of the API key, defaults to 5 characters
            validity_period_minutes: int
                The validity period of the API key in minutes, defaults to 30 days
            description: str
                A human readable description to indicate the purpose of the API key
            file: str
                The file to load/store the API keys, defaults to 'apikeys.json' in the default secrets directory.
                You need to overload both `global_config.TEMP_DIR` and this filename to use a different location.
            allowed_characters: str
                The characters to use for generating the API key, defaults to alphanumeric characters and underscore
            prefix: str
                The prefix for the API key, defaults to "wotdat" (web of things device authentication token)
            print_value: bool
                Whether to print the generated API key to the console once generated, defaults to `True`. If set to
                `False`, use the value returned by this method.
            override: bool
                Whether to override an existing API key with the same name, defaults to `False`

            Returns
            -------
            str
                The generated API key
            """
            id = "".join(secrets.choice(allowed_characters) for _ in range(id_size))
            secret = "".join(secrets.choice(allowed_characters) for _ in range(size))
            apikey = f"{prefix}-{id}.{secret}"
            hash = self.hash(apikey)
            record = APIKeyRecord(
                name=self.name,
                id=id,
                apikey_hash=hash,
                description=description,
                created_at=datetime.now().isoformat(),
                expiry_at=(datetime.now() + timedelta(minutes=validity_period_minutes)).isoformat(),
                hasher="argon2",  # currently only argon2 is supported
            )
            self.save(record=record, filename=file, override=override)
            if print_value:
                print(
                    f"API key created and saved successfully, your key is: {apikey}, "
                    + "please store it securely as it cannot be retrieved later."
                )
            return apikey

        def hash(self, apikey: str) -> str:
            """
            Create a hash of the API key for storage

            Returns
            -------
            str
                The hashed API key
            """
            return self._ph.hash(apikey)

        def save(self, record: APIKeyRecord, filename: str = "apikeys.json", override: bool = False) -> None:
            """Save the security scheme data to persistent storage"""
            filepath = os.path.join(global_config.TEMP_DIR_SECRETS, filename)
            existing_data = {}
            if os.path.exists(filepath):
                with open(filepath, "r") as file:
                    existing_data = json.load(file)
            if not override and existing_data.get(self.name, None):
                raise ValueError(f"API key with name '{self.name}' already exists, use override=True to overwrite")
            existing_data[self.name] = record.model_dump()
            with open(filepath, "w") as file:
                json.dump(existing_data, file, indent=4)

        def load(self) -> None:
            """load the security scheme data from persistent storage"""
            if not os.path.exists(self.file):
                return
            with open(self.file, "r") as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    raise ValueError("Invalid API key storage format, expected a dictionary")
                if not data.get(self.name, None):
                    return
                self.record = APIKeyRecord.model_validate(data[self.name])

        def validate_input(self, apikey: str) -> bool:
            """
            Validate an API key against a stored hash. API key ID, expiry and hash are all validated.

            Returns
            -------
            bool
                True if the API key is valid, False otherwise
            """
            if self.record is None:
                raise ValueError("No API key loaded for validation")
            try:
                id = apikey.split(".", 1)[0].split("-", 1)[1]
                if self.record.id != id:
                    return False
            except IndexError:
                return False
            if datetime.now() > self.record.expiry_at:
                return False
            try:
                return self._ph.verify(self.record.apikey_hash, apikey)
            except argon2.exceptions.VerifyMismatchError:
                return False

except ImportError:

    class APIKeySecurity(Security):
        """
        Placeholder for APIKeySecurity when argon2 is not installed.
        Please install the `argon2-cffi` library to use API key security and see the actual docstrings.
        """

        def __init__(self, name: str, file: str = "apikeys.json") -> None:
            raise ImportError("argon2-cffi library is required for APIKeySecurity")


try:
    import jwt

    from jwt import PyJWKClient

    class OIDCSecurity(Security):
        """
        Generic OIDC JWT validation meant to be used with 'openid' scope to validate login sessions, requires the PyJWT
        library to be installed. A *JWT access token* is validated by verifying its signature against the provider's
        JWKS endpoint (JWK Set) and optionally validating issuer/audience.

        This security scheme is not meant to be used with OAuth flows where the resource server is a third party
        application from where data is fetched on behalf of the user. The server using this scheme is expected to
        be the resource server itself, validating tokens issued by an identity provider.

        Parameters one will typically set:

        - `issuer`: The expected token issuer (`iss` claim). For OIDC this is usually the provider's issuer URL.
        - `audience`: The expected audience (`aud` claim). Often the OAuth2 client id.
        - `jwks_url`: The JWKS URL. If omitted, it is discovered via: `{issuer}/.well-known/openid-configuration`.
        """

        issuer: str
        audience: str | None = None
        jwks_url: str | None = None
        algorithms: list[str] = ["RS256"]
        verify_ssl: bool = True

        allowed_roles: list[str] | None = None
        role_claim_paths: list[str] | None = None

        name: str = "oidc-security"

        _jwk_client: PyJWKClient = PrivateAttr()

        def __init__(
            self,
            issuer: str,
            audience: str | None,
            jwks_url: str | None = None,
            algorithms: list[str] | None = None,
            verify_ssl: bool = True,
            allowed_roles: list[str] | None = None,
            role_claim_paths: list[str] | None = None,
            name: str = "oidc-security",
        ) -> None:
            """
            Parameters
            ----------
            issuer: str
                OIDC provider's issuer URL. This is considered to be the `iss` claim in the JWT.
            audience: str | None
                Expected audience (`aud` claim) in the JWT. Optional but highly recommended.
                The audience is often the OAuth2 client id.
            jwks_url: str | None
                The JWKS URL to fetch signing keys from. If not provided, it is discovered via
                `{issuer}/.well-known/openid-configuration`.
            algorithms: list[str] | None
                List of acceptable signing algorithms. Default is `["RS256"]`.
            verify_ssl: bool
                Whether to verify SSL certificates while connecting to the provider. Default is `True`.
            allowed_roles: list[str] | None
                List of allowed roles. If provided, the JWT must contain at least one of these roles
                in order to be considered valid.
            role_claim_paths: list[str] | None
                List of claim paths to look for roles in the JWT. If not provided, a set of common
                claim paths will be used, which are `roles`, `role`, `realm_access.roles`, `scp`, `scope`,
                and `resource_access.{aud}.roles`.
            """
            jwks_url = jwks_url or self._discover_jwks_uri(issuer=issuer, verify_ssl=verify_ssl)

            super().__init__(
                issuer=issuer,
                audience=audience,
                jwks_url=jwks_url,
                algorithms=algorithms or ["RS256"],
                verify_ssl=verify_ssl,
                allowed_roles=allowed_roles,
                role_claim_paths=role_claim_paths,
            )

            # NOTE: PyJWKClient doesn't expose SSL context configuration directly. When verify_ssl is False
            # we still validate tokens if keys can be fetched; this primarily affects transport security.
            self._jwk_client = PyJWKClient(self.jwks_url)

            if self.role_claim_paths is None:
                # Common role claim locations across providers (Keycloak included).
                self.role_claim_paths = [
                    "realm_access.roles",
                    "resource_access.{aud}.roles",
                    "roles",
                    "role",
                    "scp",
                    "scope",
                ]
                # For example, Keycloak uses `realm_access.roles` and `resource_access.{aud}.roles`.
                # "realm_access": {
                #   "roles": [
                #     "offline_access",
                #     "default-roles-hololinked-test",
                #     "uma_authorization",
                #     "device-admin" # our added roles for example
                #   ]
                # }
            self.name = name

        @staticmethod
        def _discover_jwks_uri(issuer: str, verify_ssl: bool) -> str:
            issuer = issuer.rstrip("/")
            discovery_url = f"{issuer}/.well-known/openid-configuration"

            try:
                with httpx.Client(verify=verify_ssl, timeout=10.0) as client:
                    resp = client.get(discovery_url, headers={"Accept": "application/json"})
                    resp.raise_for_status()
                    data = resp.json()  # type: dict[str, Any]
            except Exception as ex:
                raise ValueError(f"Failed to discover OIDC configuration from {discovery_url}: {ex}") from ex

            jwks_uri = data.get("jwks_uri")
            if not jwks_uri:
                raise ValueError(f"OIDC discovery document at {discovery_url} missing 'jwks_uri'")
            return jwks_uri

        @staticmethod
        def _get_dict_attr_by_path(payload: dict[str, Any], path: str) -> Any:
            """Get a nested value from a dict using dot-separated keys."""
            cur: Any = payload
            for part in path.split("."):
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(part)
            return cur

        def decode_and_validate(self, token: str) -> dict[str, Any]:
            """Decode and validate a JWT, returning the verified payload."""
            signing_key = self._jwk_client.get_signing_key_from_jwt(token).key
            options = dict(
                verify_signature=True,
                verify_exp=True,
                verify_aud=self.audience is not None,
                verify_iss=True,
            )
            return jwt.decode(
                token,
                signing_key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options=options,
            )

        def validate_input(self, jwt_token: str) -> bool:
            """Validate a JWT access token."""
            try:
                self.decode_and_validate(jwt_token)
                return True
            except Exception:
                return False

        def userinfo(self, jwt_token: str) -> dict[str, Any]:
            """Return the verified JWT claims. This does not call a remote userinfo endpoint."""
            return self.decode_and_validate(jwt_token)

        def user_has_role(self, claims: dict[str, Any]) -> bool:
            """Return True if any configured allowed role is present in the JWT claims."""
            if not self.allowed_roles:
                return True

            aud = self.audience or ""
            role_paths = [(p.format(aud=aud) if "{aud}" in p else p) for p in (self.role_claim_paths or [])]

            roles: set[str] = set()
            for path in role_paths:
                value = self._get_dict_attr_by_path(claims, path)
                if value is None:
                    continue
                if isinstance(value, str):
                    # Common for "scope" / "scp" claims.
                    roles.update(value.split())
                elif isinstance(value, list):
                    roles.update(str(v) for v in value)

            return any(r in roles for r in self.allowed_roles)

    class KeycloakOIDCSecurity(OIDCSecurity):
        """
        Keycloak specific OIDC security, extends the generic `OIDCSecurity` class.
        Only adds convenience around constructing the issuer URL. See `OIDCSecurity` for actual details and usage.
        Keycloak issuer is typically: {server_url}/realms/{realm}
        """

        def __init__(
            self,
            oidc_server_url: str,
            oidc_client_id: str,
            oidc_realm: str,
            allowed_roles: list[str] | None = None,
            verify_ssl: bool = True,
        ) -> None:
            issuer = f"{oidc_server_url.rstrip('/')}/realms/{oidc_realm}"
            super().__init__(
                issuer=issuer,
                audience=oidc_client_id,
                verify_ssl=verify_ssl,
                allowed_roles=allowed_roles,
            )

except ImportError:

    class OIDCSecurity(Security):
        """
        Placeholder for OIDCSecurity when PyJWT is not installed.
        If you see this doc, you need to install the `PyJWT` library to use OIDC security.
        """

        def __init__(
            self,
            issuer: str,
            audience: str | None = None,
            jwks_url: str | None = None,
            algorithms: list[str] | None = None,
            verify_ssl: bool = True,
            allowed_roles: list[str] | None = None,
            role_claim_paths: list[str] | None = None,
        ) -> None:
            raise ImportError("PyJWT library is required for OIDCSecurity")

    class KeycloakOIDCSecurity(Security):
        """
        Placeholder for KeycloakOIDCSecurity.
        If you see this doc, you need to install the `PyJWT` library to use OIDC security.
        """

        def __init__(
            self,
            oidc_server_url: str,
            oidc_client_id: str,
            oidc_realm: str,
            oidc_client_secret: str | None = None,
            allowed_roles: list[str] | None = None,
            verify_ssl: bool = True,
        ) -> None:
            raise ImportError("PyJWT library is required for KeycloakOIDCSecurity")
