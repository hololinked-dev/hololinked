"""
Implementation of security schemes for a server.
"""

import base64
import json
import os
import secrets
import string

from datetime import datetime

from pydantic import BaseModel, PrivateAttr

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
                An optional unique name for the security scheme
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
    pass

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
    pass


class APIKeySecurity(Security):
    """
    An API key based security scheme.

    The request must supply an authorization header in of the following formats:

    - `X-API-Key: apikey`

    """

    allowed_characters: str
    size: int = 16
    id_size: int = 5
    name: str

    _ph: argon2.PasswordHasher = PrivateAttr()

    def __init__(
        self,
        name: str,
        size: int = 16,
        **kwargs,
    ) -> None:
        super().__init__(
            name=name or f"api-key-{uuid_hex()}",
            size=size,
            id_size=kwargs.get("id_size", 5),
            allowed_characters=kwargs.get("allowed_characters", string.ascii_letters + string.digits + "_"),
        )
        self._ph = argon2.PasswordHasher()

    @classmethod
    def create(self, validity_period_minutes: int | None = None) -> str:
        """Create a new API key

        Returns
        -------
        str
            The generated API key
        """
        id = "".join(secrets.choice(self.allowed_characters) for _ in range(self.id_size))
        secret = "".join(secrets.choice(self.allowed_characters) for _ in range(self.size))
        return f"wotpat-{id}.{secret}"

    @classmethod
    def hash(self, api_key: str) -> str:
        """Create a hash of the API key for storage

        Returns
        -------
        str
            The hashed API key
        """
        return self._ph.hash(api_key)

    @classmethod
    def save(
        self,
        apikey: str,
        description: str = "API Key for WoT applications",
        filename: str = "apikeys.json",
    ) -> None:
        """
        Save the security scheme to persistent storage

        This is a placeholder method and should be implemented to save the security scheme
        to a database or file as needed.
        """
        data = dict(
            name=self.name,
            apikey=apikey,
            created_at=datetime.now().isoformat(),
            description=description,
            id=apikey.split("-")[1].split(".")[0],
        )
        with open(os.path.join(global_config.TEMP_DIR_SECRETS, filename), "w") as f:
            json.dump(data, f, indent=4)

    def validate_input(self, apikey: str) -> bool:
        """
        Validate an API key against a stored hash

        Returns
        -------
        bool
            True if the API key is valid, False otherwise
        """
        try:
            prehashed_apikey = ""
            return self._ph.verify(prehashed_apikey, apikey)
        except argon2.exceptions.VerifyMismatchError:
            return False
