# import bycrpyt


class SecurityScheme: 
    pass 

class BasicSecurity(SecurityScheme):
    username: str 
    password: str

    def validate(self, username: str, password: str) -> bool: 
        if not (username == self.username and password == self.password):
            return False
        return True
    
class KeycloakJWT(SecurityScheme):
    OIDC_CLIENT_ID: str 
    OIDC_CLIENT_SECRET: str

    def __init__():
        pass 

    def validate(self, jwt: str):
        userinfo = self.keycloak_client.userinfo()
        