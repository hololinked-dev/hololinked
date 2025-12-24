"""Implementation of security schemes for a server"""

import base64
import json
import os
import secrets
import string

from datetime import datetime, timedelta
from typing import Any

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
        """Placeholder for BcryptBasicSecurity when bcrypt is not installed"""

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
        """Placeholder for Argon2BasicSecurity when argon2 is not installed"""

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
        """Placeholder for APIKeySecurity when argon2 is not installed"""

        def __init__(self, name: str, file: str = "apikeys.json") -> None:
            raise ImportError("argon2-cffi library is required for APIKeySecurity")


try:
    from keycloak import KeycloakAdmin, KeycloakAuthenticationError, KeycloakOpenID

    class KeycloakOAuth2Security(Security):
        """Placeholder for KeycloakOAuth2Security"""

        oidc_server_url: str
        """URL of the OIDC server"""

        oidc_client_id: str
        """Client ID registered with the OIDC server"""

        oidc_realm: str
        """Realm name in the OIDC server"""

        oidc_client_secret: str | None = None
        """
        Client secret registered with the OIDC server, necessary for retrieving confidential information 
        like user roles. Not necessary for basic token validation and recomended to leave it `None`.
        """

        verify_ssl: bool = True
        """Whether to verify SSL certificates"""

        allowed_roles: list[str] | None = None
        """
        List of allowed roles which users need for access, `None` means no role-based restriction.
        Please don't confuse it with a detailed RBAC implementation.
        """

        _keycloak_client: KeycloakOpenID = PrivateAttr()

        def __init__(
            self,
            oidc_server_url: str,
            oidc_client_id: str,
            oidc_realm: str,
            oidc_client_secret: str | None = None,
            allowed_roles: list[str] | None = None,
            verify_ssl: bool = True,
        ) -> None:
            super().__init__(
                oidc_server_url=oidc_server_url,
                oidc_client_id=oidc_client_id,
                oidc_realm=oidc_realm,
                oidc_client_secret=oidc_client_secret,
                allowed_roles=allowed_roles,
                verify_ssl=verify_ssl,
            )
            self._keycloak_client = KeycloakOpenID(
                server_url=oidc_server_url,
                client_id=oidc_client_id,
                realm_name=oidc_realm,
                verify=verify_ssl,
            )
            if oidc_client_secret:
                self._admin_keycloak_client = KeycloakAdmin(
                    server_url=oidc_server_url,
                    realm_name=oidc_realm,  # moslty no need master realm, TODO check this logic later
                    user_realm_name=oidc_realm,
                    client_id=oidc_client_id,
                    client_secret_key=oidc_client_secret,
                    verify=verify_ssl,
                )

        def validate_input(self, jwt: str) -> bool:
            try:
                self._keycloak_client.userinfo(token=jwt)
                return True
            except KeycloakAuthenticationError:
                return False

        async def async_validate_input(self, jwt: str) -> bool:
            """Asynchronous validation is not implemented yet"""
            try:
                await self._keycloak_client.a_userinfo(token=jwt)
                return True
            except KeycloakAuthenticationError:
                return False

        def userinfo(self, jwt: str) -> dict[str, Any]:
            """Get user info from the JWT token"""
            return self._keycloak_client.userinfo(token=jwt)

        async def async_userinfo(self, jwt: str) -> dict[str, Any]:
            """Get user info from the JWT token asynchronously"""
            return await self._keycloak_client.a_userinfo(token=jwt)

        def user_has_role(self, userinfo: dict) -> bool:
            """Check if the client has a specific role"""
            if not self.allowed_roles:
                return True
            if not self._admin_keycloak_client:
                raise ValueError("Client secret is required to check roles")
            realm_roles = self._admin_keycloak_client.get_realm_roles_of_user(user_id=userinfo["sub"])
            for rolename in self.allowed_roles:
                if any(role.get("name") == rolename for role in realm_roles):
                    return True
            return False

        async def async_user_has_role(self, userinfo: dict) -> bool:
            """Asynchronous role checking is not implemented yet"""
            if not self.allowed_roles:
                return True
            if not self._admin_keycloak_client:
                raise ValueError("Client secret is required to check roles")
            realm_roles = await self._admin_keycloak_client.a_get_realm_roles_of_user(user_id=userinfo["sub"])
            for rolename in self.allowed_roles:
                if any(role.get("name") == rolename for role in realm_roles):
                    return True
            return False

except ImportError:

    class KeycloakOAuth2Security(Security):
        """Placeholder for KeycloakOAuth2Security when keycloak library is not installed"""

        def __init__(
            self,
            oidc_server_url: str,
            oidc_client_id: str,
            oidc_realm: str,
            verify_ssl: bool = True,
        ) -> None:
            raise ImportError("keycloak library is required for KeycloakOAuth2Security")
