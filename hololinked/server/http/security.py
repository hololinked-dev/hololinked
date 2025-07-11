

class BasicSecurity:
    username: str 
    password: str

    def validate(self, username: str, password: str) -> bool: 
        if not (username == self.username and password == self.password):
            return False
        return True