"""
Implementation of security schemes for a server.
"""

class SecurityScheme: 
    """Type definition for security schemes"""
    pass 

try:
    import bcrypt

    class BcryptBasicSecurity(SecurityScheme):
        username: str
        _password_hash: bytes
        expect_base64: bool 

        def __init__(self, username: str, password: str, expect_base64: bool = False) -> None:
            self.username = username
            self._password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            del password  # Remove password from memory
            self.expect_base64 = expect_base64

        def validate(self, username: str, password: str) -> bool:
            if self.expect_base64:
                try:
                    password = password.encode('utf-8')
                    password = bcrypt.decode_base64(password)
                except ValueError:
                    return False
            if username != self.username:
                return False
            return bcrypt.checkpw(password.encode('utf-8'), self._password_hash)
except ImportError:
    pass 

try:
    import argon2
    class Argon2BasicSecurity(SecurityScheme):
        username: str
        _password_hash: str
        expect_base64: bool

        def __init__(self, username: str, password: str, expect_base64: bool = False) -> None:
            self.ph = argon2.PasswordHasher()
            self.username = username
            self.expect_base64 = expect_base64
            self._password_hash = self.ph.hash(password)
            del password  # Remove password from memory

        def validate(self, username: str, password: str) -> bool:
            if self.expect_base64:
                try:
                    password = password.encode('utf-8')
                    password = argon2.PasswordHasher().decode_base64(password)
                except ValueError:
                    return False
            if username != self.username:
                return False
            try:
                return self.ph.verify(self._password_hash, password)
            except argon2.exceptions.VerifyMismatchError:
                return False
except ImportError:
    pass

# class KeycloakJWT(SecurityScheme):
#     OIDC_CLIENT_ID: str 
#     OIDC_CLIENT_SECRET: str

#     def __init__():
#         pass 

#     def validate(self, jwt: str):
#         userinfo = self.keycloak_client.userinfo()
#