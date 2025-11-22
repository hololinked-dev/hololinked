from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.types import SecretStr, StrictInt, StrictStr


class SQLDBConfig(BaseModel):
    """Configuration validator for SQL databases for PostgreSQL and MySQL"""

    provider: Literal["postgresql", "mysql"] = "postgresql"
    """Database provider, postgresql or mysql"""
    host: StrictStr = "localhost"
    """PostgreSQL server host"""
    port: StrictInt = 5432
    """server port, default 5432"""
    database: StrictStr = "hololinked"
    """database name, default hololinked"""
    user: StrictStr = "hololinked"
    """user name, default hololinked, recommended not to use admin user"""
    password: SecretStr = Field(default=SecretStr(""), repr=False)
    """user password, default empty"""
    dialect: Literal["asyncpg", "psycopg", "asyncmy", "mysqldb", ""] = ""
    """dialect to use, default psycopg for postgresql"""
    uri: SecretStr = ""
    """Full database URI, overrides other settings, default empty"""

    model_config = ConfigDict(extra="forbid")

    @property
    def URL(self) -> str:
        if self.uri:
            return self.uri.get_secret_value()
        if self.provider == "postgresql":
            return f"postgresql{'+' + self.dialect if self.dialect else ''}://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.database}"
        return f"mysql{'+' + self.dialect if self.dialect else ''}://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.database}"

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.uri and (not self.host or not self.port or not self.database or not self.user or not self.password):
            raise ValueError("Provide either database URI or all of 'host', 'port', 'database', 'user', and 'password'")
        return self


class SQLiteConfig(BaseModel):
    """Configuration validator for SQLite database"""

    provider: Literal["sqlite"] = "sqlite"
    """Database provider, only sqlite is supported"""
    dialect: SecretStr = "pysqlite"
    """dialect to use, aiosqlite for async, pysqlite for sync"""
    file: str = ""
    """SQLite database file, default is empty string, which leads to an DB with name of thing ID"""
    in_memory: bool = False
    """Use in-memory SQLite database, default False as it is not persistent"""
    uri: SecretStr = ""
    """Full database URI, overrides other settings, default empty"""

    model_config = ConfigDict(extra="forbid")

    @property
    def URL(self) -> str:
        if self.uri:
            return self.uri.get_secret_value()
        if self.in_memory:
            return f"sqlite+{self.dialect}:///:memory:"
        elif self.file:
            return f"sqlite+{self.dialect}:///{self.file}"
        raise NotImplementedError("Either 'uri' or 'file' or 'in_memory' must be provided for SQLiteConfig")


class MongoDBConfig(BaseModel):
    """Configuration validator for MongoDB database"""

    provider: Literal["mongo"] = "mongo"
    """Database provider, only mongo is supported"""
    host: StrictStr = "localhost"
    """MongoDB server host"""
    port: StrictInt = 27017
    """server port, default 27017"""
    database: StrictStr = "hololinked"
    """database name, default hololinked"""
    user: StrictStr = ""
    """user name, default empty, recommended not to use admin user"""
    password: SecretStr = ""
    """user password, default empty"""
    authSource: StrictStr = ""
    """authentication source database, default empty"""
    uri: SecretStr = ""
    """Full database URI, overrides other settings, default empty"""

    model_config = ConfigDict(extra="forbid")

    @property
    def URL(self) -> str:
        if self.uri:
            return self.uri.get_secret_value()
        if self.user and self.password:
            if self.authSource:
                return f"mongodb://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/?authSource={self.authSource}"
            return f"mongodb://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/"
        return f"mongodb://{self.host}:{self.port}/"

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.uri and (not self.host or not self.port or not self.database or not self.user or not self.password):
            raise ValueError("Provide either database URI or all of 'host', 'port', 'database', 'user', and 'password'")
        return self
