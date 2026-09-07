"""Runtime configuration for the ZMQ server."""

from typing import Any

from pydantic import BaseModel

from hololinked.server.zmq.services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """
    Runtime configuration for the ZMQ server.

    Pass the attributes of this class as a dictionary to the `config` argument of `ZMQServer`.
    """

    thing_description_service: type[ThingDescriptionService] | Any = ThingDescriptionService
    """service class used to generate the Thing Description, with forms addressing this server's sockets"""
