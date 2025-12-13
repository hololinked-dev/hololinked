from pydantic import BaseModel


class RuntimeConfig(BaseModel):
    """Runtime configuration for HTTP server and handlers."""

    cors: bool = False
    """
    Set CORS headers for the HTTP server. If set to False, CORS headers are not set.
    This is useful when the server is used in a controlled environment where CORS is not needed.
    """


class HandlerMetadata(BaseModel):
    """Specific metadata when a request handler has been initialized"""

    http_methods: tuple[str | None, ...] = tuple()
    """HTTP methods supported by the handler."""
