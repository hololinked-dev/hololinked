"""Runtime configuration for the ZMQ server."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from hololinked.server.security import APIKeySecurity, Security
from hololinked.server.zmq.services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """
    Runtime configuration for the ZMQ server.

    Pass the attributes of this class as a dictionary to the `config` argument of `ZMQServer`.
    """

    thing_description_service: type[ThingDescriptionService] | Any = ThingDescriptionService
    """service class used to generate the Thing Description, with forms addressing this server's sockets"""

    security_schemes: list[Security] | None = Field(default=None)
    """
    List of security schemes checked against the request header `authorization: apikey <value>`.
    It is sufficient that one scheme passes for a request to be authenticated. Only `APIKeySecurity`
    is supported for ZMQ currently. `None` disables authentication, keeping existing setups unaffected.
    """

    @field_validator("security_schemes")
    @classmethod
    def validate_security_schemes(cls, value: list[Security] | None) -> list[Security] | None:
        """
        Reject schemes the ZMQ server cannot enforce, so misconfiguration fails at startup.

        A silently ignored scheme would otherwise reject every request at runtime with no clear cause.

        Parameters
        ----------
        value: list[Security] | None
            configured security schemes

        Returns
        -------
        list[Security] | None
            the same schemes, unchanged

        Raises
        ------
        ValueError
            if any scheme is not an `APIKeySecurity`
        """
        if value is None:
            return value
        unsupported = [type(scheme).__name__ for scheme in value if not isinstance(scheme, APIKeySecurity)]
        if unsupported:
            raise ValueError(f"ZMQ server supports only APIKeySecurity, got unsupported schemes: {unsupported}")
        return value
