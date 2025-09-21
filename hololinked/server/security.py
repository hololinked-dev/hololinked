"""
Implementation of security schemes for a server.
"""

import base64


class Security:
    """Type definition for security schemes"""

    pass


try:
    import bcrypt

    class BcryptBasicSecurity(Security):
        """
        A username and password based security scheme using bcrypt.
        The password is stored as a hash and will be deleted from memory after initialization
        (even if you keep a reference to the object).

        The request must supply an authorization header with the format:
        `Authorization: Basic base64(username:password)`
        The username and password are expected to be base64 encoded, by default.

        Set `expect_base64=False` if you want to use plain text credentials without base64 encoding.
        The authorization header should then be in the format:
        `Authorization: Basic username:password`

        Use bcrypt when you are constrained in terms of memory. Use Argon2BasicSecurity
        when you can afford more memory (which is the recommended username-password implementation).
        Note: bcrypt is a memory-hard hashing algorithm, which means it is resistant to brute-force attacks.
        """

        username: str
        _password_hash: bytes
        expect_base64: bool

        def __init__(self, username: str, password: str, expect_base64: bool = True) -> None:
            self.username = username
            self._password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
            del password  # Remove password from memory
            self.expect_base64 = expect_base64

        def validate(self, username: str, password: str) -> bool:
            """plain validate a username and password"""
            if username != self.username:
                return False
            return bcrypt.checkpw(password.encode("utf-8"), self._password_hash)

        def validate_base64(self, b64_str: str) -> bool:
            """Validate a base64 encoded string containing username and password"""
            if not self.expect_base64:
                raise ValueError("base64 encoded credentials not expected, please reconfigure if needed")
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8")
            except (ValueError, TypeError):
                return False
            username, password = decoded.split(":", 1)
            return self.validate(username, password)

except ImportError:
    pass

try:
    import argon2

    class Argon2BasicSecurity(Security):
        """
        A username and password based security scheme using Argon2.
        The password is stored as a hash and will be deleted from memory after initialization
        (even if you keep a reference to the object).

        The request must supply an authorization header with the format:
        `Authorization: Basic base64(username:password)`
        The username and password are expected to be base64 encoded, by default.

        Set `expect_base64=False` if you want to use plain text credentials without base64 encoding.
        The authorization header should then be in the format:
        `Authorization: Basic username:password`

        Argon2 is the recommended password hashing security scheme.
        """

        username: str
        _password_hash: str
        expect_base64: bool

        def __init__(self, username: str, password: str, expect_base64: bool = True) -> None:
            self.ph = argon2.PasswordHasher()
            self.username = username
            self.expect_base64 = expect_base64
            self._password_hash = self.ph.hash(password)
            del password  # Remove password from memory

        def validate(self, username: str, password: str) -> bool:
            if username != self.username:
                return False
            try:
                return self.ph.verify(self._password_hash, password)
            except argon2.exceptions.VerifyMismatchError:
                return False

        def validate_base64(self, b64_str: str) -> bool:
            if not self.expect_base64:
                raise ValueError("base64 encoded credentials not expected, please reconfigure if needed")
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8")
            except (ValueError, TypeError):
                return False
            username, password = decoded.split(":", 1)
            return self.validate(username, password)

except ImportError:
    pass
