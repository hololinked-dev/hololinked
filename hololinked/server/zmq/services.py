"""Service layer that generates the Thing Description served over ZMQ."""

from __future__ import annotations

import copy
import socket

from typing import Any

import structlog

from hololinked import Serializers
from hololinked.constants import Operations
from hololinked.core.thing import Thing
from hololinked.metadata.td import ActionAffordance, EventAffordance, PropertyAffordance
from hololinked.metadata.td.forms import Form


class ThingDescriptionService:
    """
    Generates Thing Descriptions for `Thing`s served over ZMQ.

    This object would be a service in layered architecture.
    """

    def __init__(self, server: Any, logger: structlog.stdlib.BoundLogger) -> None:
        """
        Initialize the Thing Description service.

        Parameters
        ----------
        server: ZMQServer
            the server whose sockets the forms address - a Thing Description is mostly forms, and a
            form is an address on one of them, which is why only this server can build one
        logger: structlog.stdlib.BoundLogger
            The logger to use for logging messages
        """
        from hololinked.server.zmq.server import ZMQServer  # noqa: F401

        self.server = server  # type: ZMQServer
        self.logger = logger.bind(layer="service", impl=self.__class__.__name__)

    def socket_addresses_for(self, protocol: str) -> tuple[str, str]:
        """
        The request and event socket addresses a form should carry for one transport.

        Parameters
        ----------
        protocol: str
            the transport to address - `INPROC`, `IPC` or `TCP`

        Returns
        -------
        tuple[str, str]
            the REQ-REP address and the PUB-SUB address, in that order

        Raises
        ------
        RuntimeError
            if the server does not serve that transport
        ValueError
            if the protocol is not one of `INPROC`, `IPC` or `TCP`
        """
        server = self.server
        if protocol.lower() == "inproc":
            if server.inproc_server is None or server.inproc_event_publisher is None:
                raise RuntimeError(
                    "This server cannot generate TD for INPROC protocol, consider using thing model directly."
                )
            return server.inproc_server.socket_address, server.inproc_event_publisher.socket_address
        if protocol.lower() == "ipc":
            if server.ipc_server is None or server.ipc_event_publisher is None:
                raise RuntimeError(
                    "This server cannot generate TD for IPC protocol, consider using thing model directly."
                )
            return server.ipc_server.socket_address, server.ipc_event_publisher.socket_address
        if protocol.lower() == "tcp":
            if server.tcp_server is None or server.tcp_event_publisher is None:
                raise RuntimeError(
                    "This server cannot generate TD for TCP protocol, consider using thing model directly."
                )
            # a socket bound to every interface is not an address a client can dial
            hostname = socket.gethostname()
            req_rep_socket_address = server.tcp_server.socket_address.replace(
                "*", hostname
            ).replace(
                "0.0.0.0",
                hostname,
            )  # SAST(id='hololinked.server.zmq.services.ThingDescriptionService.socket_addresses_for.req_rep_socket_address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
            pub_sub_socket_address = server.tcp_event_publisher.socket_address.replace(
                "*", hostname
            ).replace(
                "0.0.0.0",
                hostname,
            )  # SAST(id='hololinked.server.zmq.services.ThingDescriptionService.socket_addresses_for.pub_sub_socket_address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
            return req_rep_socket_address, pub_sub_socket_address
        raise ValueError(f"Unsupported protocol '{protocol}' for ZMQ.")

    async def generate(
        self,
        thing: Thing,
        protocol: str,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, Any]:
        """
        Generate the Thing Description for one `Thing`, with ZMQ forms for one transport.

        Parameters
        ----------
        thing: Thing
            The `Thing` whose description is generated
        protocol: str
            The protocol for which to generate the TD - `INPROC`, `IPC` or `TCP`
        ignore_errors: bool
            Whether to ignore errors while generating the TD. Default is False.
        skip_names: list[str]
            List of property, action or event names to skip while generating the TD.

        Returns
        -------
        dict[str, Any]
            The Thing Description in JSON format.

        Raises
        ------
        RuntimeError
            if the server does not serve the requested protocol
        ValueError
            if the protocol is not one of `INPROC`, `IPC` or `TCP`
        """
        TM = thing.get_thing_model(ignore_errors=ignore_errors, skip_names=skip_names).json()  # type: dict[str, Any]
        TD = copy.deepcopy(TM)
        req_rep_socket_address, pub_sub_socket_address = self.socket_addresses_for(protocol)

        self.add_properties(TD, TM, thing, req_rep_socket_address, pub_sub_socket_address, ignore_errors)
        self.add_actions(TD, TM, thing, req_rep_socket_address, ignore_errors)
        self.add_events(TD, TM, thing, pub_sub_socket_address, ignore_errors)

        return TD

    def content_type_for(self, thing: Thing, name: str) -> str:
        """
        The content type one objekt's payloads are declared with.

        Parameters
        ----------
        thing: Thing
            the `Thing` the objekt belongs to
        name: str
            name of the property, action or event

        Returns
        -------
        str
            the registered content type, or the one its serializer declares
        """
        content_type = Serializers.get_content_type_for_object(thing.id, thing.__class__.__name__, name)
        if not content_type:
            content_type = Serializers.for_object(thing.id, thing.__class__.__name__, name).content_type
        return content_type

    def add_properties(
        self,
        TD: dict[str, Any],
        TM: dict[str, Any],
        thing: Thing,
        req_rep_socket_address: str,
        pub_sub_socket_address: str,
        ignore_errors: bool,
    ) -> None:
        """
        Add properties to the TD with ZMQ forms, one per operation the property supports.

        Parameters
        ----------
        TD: dict[str, Any]
            The Thing Description to modify in place
        TM: dict[str, Any]
            The Thing Model the description is built from
        thing: Thing
            The `Thing` being described
        req_rep_socket_address: str
            address reads and writes are addressed to
        pub_sub_socket_address: str
            address change events are addressed to
        ignore_errors: bool
            Whether to warn and carry on rather than raise
        """
        for name in TM.get("properties", []):
            try:
                affordance = PropertyAffordance.from_TD(name, TM)
                if not TD["properties"][name].get("forms", None):
                    TD["properties"][name]["forms"] = []
                content_type = self.content_type_for(thing, name)

                form = Form()
                form.href = req_rep_socket_address
                form.op = Operations.readproperty
                form.contentType = content_type
                TD["properties"][name]["forms"].append(form.json())

                if not affordance.readOnly:
                    form = Form()
                    form.href = req_rep_socket_address
                    form.op = Operations.writeproperty
                    form.contentType = content_type
                    TD["properties"][name]["forms"].append(form.json())

                if affordance.observable:
                    form = Form()
                    form.href = pub_sub_socket_address
                    form.op = Operations.observeproperty
                    form.contentType = content_type
                    TD["properties"][name]["forms"].append(form.json())
            except Exception as ex:
                if not ignore_errors:
                    raise ex from None
                thing.logger.warning(
                    "error while generating TD forms for property",
                    name=name,
                    error=str(ex),
                )

    def add_actions(
        self,
        TD: dict[str, Any],
        TM: dict[str, Any],
        thing: Thing,
        req_rep_socket_address: str,
        ignore_errors: bool,
    ) -> None:
        """
        Add actions to the TD with ZMQ forms.

        Parameters
        ----------
        TD: dict[str, Any]
            The Thing Description to modify in place
        TM: dict[str, Any]
            The Thing Model the description is built from
        thing: Thing
            The `Thing` being described
        req_rep_socket_address: str
            address invocations are addressed to
        ignore_errors: bool
            Whether to warn and carry on rather than raise
        """
        for name in TM.get("actions", []):
            try:
                ActionAffordance.from_TD(name, TM)
                if not TD["actions"][name].get("forms", None):
                    TD["actions"][name]["forms"] = []

                form = Form()
                form.href = req_rep_socket_address
                form.op = Operations.invokeaction
                form.contentType = self.content_type_for(thing, name)
                TD["actions"][name]["forms"].append(form.json())
            except Exception as ex:
                if not ignore_errors:
                    raise ex from None
                thing.logger.warning(
                    "error while generating TD forms for action",
                    name=name,
                    error=str(ex),
                )

    def add_events(
        self,
        TD: dict[str, Any],
        TM: dict[str, Any],
        thing: Thing,
        pub_sub_socket_address: str,
        ignore_errors: bool,
    ) -> None:
        """
        Add events to the TD with ZMQ forms.

        Parameters
        ----------
        TD: dict[str, Any]
            The Thing Description to modify in place
        TM: dict[str, Any]
            The Thing Model the description is built from
        thing: Thing
            The `Thing` being described
        pub_sub_socket_address: str
            address subscriptions are addressed to
        ignore_errors: bool
            Whether to warn and carry on rather than raise
        """
        for name in TM.get("events", []):
            try:
                EventAffordance.from_TD(name, TM)
                if not TD["events"][name].get("forms", None):
                    TD["events"][name]["forms"] = []

                form = Form()
                form.href = pub_sub_socket_address
                form.op = Operations.subscribeevent
                form.contentType = self.content_type_for(thing, name)
                TD["events"][name]["forms"].append(form.json())
            except Exception as ex:
                if not ignore_errors:
                    raise ex from None
                thing.logger.warning(
                    "error while generating TD forms for event",
                    name=name,
                    error=str(ex),
                )


__all__ = [ThingDescriptionService.__name__]
