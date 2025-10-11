from pydantic import BaseModel, Field


class SQLDBConfig(BaseModel):
    """Configuration validator for SQL databases for PostgreSQL and MySQL"""

    provider: str = Field("postgresql", pattern="^(postgresql|mysql)$")
    """Database provider, postgresql or mysql"""
    host: str = Field("localhost")
    """PostgreSQL server host"""
    port: int = Field(5432)
    """server port, default 5432"""
    database: str = Field("hololinked")
    """database name, default hololinked"""
    user: str = Field("hololinked")
    """user name, default hololinked, recommended not to use admin user"""
    password: str = Field("")
    """user password, default empty"""
    dialect: str = Field("", pattern="^(asyncpg|psycopg|asyncmy|mysqldb)$")
    """dialect to use, default psycopg for postgresql"""

    @property
    def URL(self) -> str:
        if self.provider == "postgresql":
            return f"postgresql{'+' + self.dialect if self.dialect else ''}://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        return f"mysql{'+' + self.dialect if self.dialect else ''}://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class SQLiteConfig(BaseModel):
    """Configuration validator for SQLite database"""

    provider: str = Field("sqlite", pattern="^(sqlite)$")
    """Database provider, only sqlite is supported"""  #
    dialect: str = Field("pysqlite", pattern="^(aiosqlite|sqlite)$")
    """dialect to use, aiosqlite for async, pysqlite for sync"""
    file: str = Field("")
    """SQLite database file, default is empty string, which leads to an DB with name of thing ID"""
    in_memory: bool = Field(False, description="Use in-memory SQLite database")
    """Use in-memory SQLite database, default False as it is not persistent"""

    @property
    def sqlite_url(self) -> str:
        if self.in_memory:
            return f"sqlite+{self.dialect}:///:memory:"
        return f"sqlite+{self.dialect}:///{self.file}"


class MongoDBConfig(BaseModel):
    """Configuration validator for MongoDB database"""

    provider: str = Field("mongodb", pattern="^(mongodb)$")
    """Database provider, only mongodb is supported"""
    host: str = Field("localhost")
    """MongoDB server host"""
    port: int = Field(27017)
    """server port, default 27017"""
    database: str = Field("hololinked")
    """database name, default hololinked"""
    user: str = Field("")
    """user name, default empty, recommended not to use admin user"""
    password: str = Field("")
    """user password, default empty"""
    authSource: str = Field("")
    """authentication source database, default empty"""

    @property
    def URL(self) -> str:
        if self.user and self.password:
            if self.authSource:
                return f"mongodb://{self.user}:{self.password}@{self.host}:{self.port}/?authSource={self.authSource}"
            return f"mongodb://{self.user}:{self.password}@{self.host}:{self.port}/"
        return f"mongodb://{self.host}:{self.port}/"
