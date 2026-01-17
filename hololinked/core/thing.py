import inspect
import logging
import ssl

from typing import Any

import structlog

from ..constants import ZMQ_TRANSPORTS
from ..serializers import Serializers
from ..utils import forkable, getattr_without_descriptor_read
from .actions import BoundAction, action
from .events import EventDispatcher
from .meta import EventSource, Propertized, RemoteInvokable, ThingMeta
from .properties import ClassSelector, String
from .property import Property


class Thing(Propertized, RemoteInvokable, EventSource, metaclass=ThingMeta):
    """
    Subclass from here to expose hardware or python objects on the network. Remotely accessible members of a `Thing` are
    segregated into properties, actions & events. Utilize properties for data that can be read and written,
    actions to instruct the object to perform tasks and events to get notified of any relevant information. State Machines
    can be used to constrain operations on properties and actions.

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/Thing.pdf)
    """

    # local properties
    id = String(
        default=None,
        regex=r"[A-Za-z]+[A-Za-z_0-9\-\/]*",
        constant=True,
        remote=False,
        doc="""String identifier of the instance. For an interconnected system of hardware, 
            IDs are recommended to be unique. This value is used for many operations,
            for example - creating zmq socket address, tables in databases, and to identify the instance 
            in the HTTP Server - (http(s)://{domain and sub domain}/{id}).""",
    )  # type: str
    """
    String identifier of the instance. For an interconnected system of hardware, 
    IDs are recommended to be unique. This value is used for many operations,
    for example - creating zmq socket address, tables in databases, and to identify the instance 
    in the HTTP Server - (http(s)://{domain}/{id}).
    """
    # TODO use docstring in only one place

    logger = ClassSelector(
        class_=(logging.Logger, structlog.stdlib.BoundLoggerBase),
        default=None,
        allow_None=True,
        remote=False,
        doc="""structlog.stdlib.BoundLogger instance to log messages. Default logger with a IO-stream handler 
            is created if none supplied.""",
    )  # type: structlog.stdlib.BoundLoggerBase
    """
    structlog.stdlib.BoundLogger instance to log messages. Default logger with a IO-stream handler 
    is created if none supplied.
    """

    state_machine = None  # type: "StateMachine" | None
    """class property reserved for state machine instance if any."""

    # remote properties
    state = String(
        default=None,
        allow_None=True,
        readonly=True,
        observable=True,
        fget=lambda self: self.state_machine.current_state if self.state_machine else None,
        doc="""Current state machine's state if state machine present, `None` indicates absence of state machine.
            State machine returned state is always a string even if specified as an Enum in the state machine.""",
    )  # type: str | None
    """
    Current state machine's state if state machine present, `None` indicates absence of state machine.
    State machine returned state is always a string even if specified as an Enum in the state machine.
    """

    # object_info = Property(doc="contains information about this object like the class name, script location etc.") # type: ThingInformation

    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        # defines some internal fixed attributes. attributes created by us that require no validation but
        # cannot be modified are called _internal_fixed_attributes
        obj._internal_fixed_attributes = ["_internal_fixed_attributes", "_owners"]
        return obj

    def __init__(
        self,
        *,
        id: str,
        logger: structlog.stdlib.BoundLogger | None = None,
        **kwargs: dict[str, Any],
    ) -> None:
        """
        Parameters
        ----------
        id: str
            String identifier of the instance. For an interconnected system of hardware,
            IDs are recommended to be unique. This value is used for many operations, for example -
            creating zmq socket address, tables in databases, and to identify the instance in a
            HTTP Server - (http(s)://{domain and sub domain}/{id}).
        logger: structlog.stdlib.BoundLogger, optional
            `structlog.stdlib.BoundLogger` instance to log messages. Default logger with a IO-stream handler
            is created if None supplied.
        **kwargs: dict[str, Any]

            - `serializer`: `BaseSerializer` | `JSONSerializer`, optional
                Default serializer to be used for serializing and deserializing data.
                If not supplied, a `msgspec` based JSON Serializer is used.
            - `remote_accessible_logger`: `bool`, Default `False`.
                if `True`, the log records can be streamed by a remote client. `remote_accessible_logger` can also be set as a
                class attribute. Use this a minimalistic replacement for fluentd or similar log collectors.
            - `use_default_db`: `bool`, Default `False`.
                if `True`, default SQLite database is created where properties can be stored and loaded. There is no need to supply
                any database credentials. `use_default_db` value can also be set as a class attribute.
            - `db_config_file`: `str`, optional.
                if not using a default database, supply a JSON configuration file to create a database connection. Check documentaion
                of [`hololinked.core.database`](https://docs.hololinked.dev/api-reference/namespaces/).
            - `use_json_file`: `bool`, Default `False`
                if `True`, a JSON file will be used as the property storage instead of a database. This value can also be
                set as a class attribute.
            - `json_filename`: `str`, optional
                If using JSON storage, this filename is used to persist property values. If not provided, a default filename
                is generated based on the instance name.
        """
        Propertized.__init__(self, id=id, logger=logger, **kwargs)
        RemoteInvokable.__init__(self)
        EventSource.__init__(self)
        if self.id.startswith("/"):
            self.id = self.id[1:]
        if kwargs.get("serializer", None) is not None:
            Serializers.register_for_thing_instance(self.id, kwargs.get("serializer"))

        from .logger import prepare_object_logger  # noqa
        from .state_machine import prepare_object_FSM  # noqa
        from ..storage import prepare_object_storage  # noqa

        prepare_object_logger(
            instance=self,
            remote_access=kwargs.get(
                "remote_accessible_logger",
                self.__class__.remote_accessible_logger
                if hasattr(self.__class__, "remote_accessible_logger")
                else False,
            ),
        )
        prepare_object_FSM(self)
        prepare_object_storage(self, **kwargs)  # use_default_db, db_config_file, use_json_file, json_filename

        self._qualified_id = self.id  # filler for now - TODO
        # thing._qualified_id = f'{self._qualified_id}/{thing.id}'

    def __post_init__(self):
        from ..storage.database import ThingDB
        from .logger import RemoteAccessHandler
        from .zmq.rpc_server import RPCServer  # noqa: F401

        # Type definitions
        self.rpc_server = None  # type: RPCServer | None
        self.db_engine: ThingDB | None
        self._owners = None if not hasattr(self, "_owners") else self._owners  # type: list[Thing] | None
        self._remote_access_loghandler: RemoteAccessHandler | None
        self._internal_fixed_attributes: list[str]
        self._qualified_id: str
        self._state_machine_state: str
        # database operations
        self.properties.load_from_DB()
        # object is ready
        self.logger.info(f"initialialised Thing class {self.__class__.__name__} with id {self.id}")

    def __setattr__(self, __name: str, __value: Any) -> None:
        if __name == "_internal_fixed_attributes" or __name in self._internal_fixed_attributes:
            # order of 'or' operation for above 'if' matters
            if not hasattr(self, __name) or getattr(self, __name, None) is None:
                # allow setting of fixed attributes once
                super().__setattr__(__name, __value)
            else:
                raise AttributeError(
                    f"Attempted to set {__name} more than once. "
                    + "Cannot assign a value to this variable after creation."
                )
        else:
            super().__setattr__(__name, __value)

    @property
    def sub_things(self) -> dict[str, "Thing"]:
        """other `Thing`s' that are composed within this `Thing`."""
        things = dict()
        for name, subthing in inspect._getmembers(
            self,
            lambda obj: isinstance(obj, Thing),
            getattr_without_descriptor_read,  # noqa: F405
        ):
            if not hasattr(subthing, "_owners") or subthing._owners is None:
                subthing._owners = []
            if self not in subthing._owners:
                subthing._owners.append(self)
            things[name] = subthing
        return things

    @action()
    def get_thing_model(self, ignore_errors: bool = False, skip_names: list[str] = []):
        """
        generate the [Thing Model](https://www.w3.org/TR/wot-thing-description11/#introduction-tm) of the object.
        The model is a JSON that describes the object's properties, actions, events and their metadata, without the
        protocol information. The model can be used by a client to understand the object's capabilities.

        Parameters
        ----------
        ignore_errors: `bool`, optional, Default `False`
            if `True`, offending interaction affordances will be removed from the JSON
            (i.e. those who have wrong metadata or non-JSON metadata).
            This is useful to build partial but always working `ThingModel`.
        skip_names: `list[str]`, optional
            List of affordances names (of any type) to skip in the generated model.

        Returns
        -------
        hololinked.td.ThingModel
            represented as an object in python, gets automatically serialized to JSON when pushed out of the socket.
        """
        # allow_loose_schema: bool, optional, Default False
        #     Experimental properties, actions or events for which schema was not given will be supplied with a suitable
        #     inaccurate but truthy value. In other words, schema validation will always pass.
        from ..td.tm import ThingModel

        return ThingModel(instance=self, ignore_errors=ignore_errors, skip_names=skip_names).generate()

    thing_model = property(get_thing_model, doc=get_thing_model.__doc__)

    @forkable  # noqa: F405
    def run_with_zmq_server(
        self,
        access_points: list[ZMQ_TRANSPORTS] | ZMQ_TRANSPORTS | str | list[str] = ZMQ_TRANSPORTS.IPC,
        forked: bool = False,  # used by decorator
        **kwargs: dict[str, Any],
    ) -> None:
        """
        Quick-start to serve `Thing` over ZMQ. This method is fully blocking, call `exit()` (`hololinked.server.exit()`)
        to unblock.

        Parameters
        ----------
        access_points: list[ZMQ_TRANSPORTS] | ZMQ_TRANSPORTS | str | list[str], Default ZMQ_TRANSPORTS.IPC or "IPC"
            ZMQ transport layers at which the object is exposed:

            - `TCP` -  custom implemented protocol in plain TCP - supply a socket address additionally in the format
            `tcp://*:<port>` (for example - `tcp://*:5555`) or a random port will be automatically used.
            The star `*` indicates that the server will listen on all available network interfaces.
            - `IPC` - inter process communication - connection can be made from other processes running
            locally within same computer. No client on the network will be able to contact the object using
            this transport. Use this transport if you wish to avoid configuring your firewall for a local client,
            like a Desktop application or a local web server.
            - `INPROC` - one main python process spawns several threads in one of which the `Thing`
            will be running. The object can be contacted by a client on another thread but not from other processes
            or the network.

            One may use more than one form of transport.  All requests made will be anyway queued internally
            irrespective of origin. For multiple transports, supply a list of transports.
            For example: `[ZMQ_TRANSPORTS.TCP, ZMQ_TRANSPORTS.IPC]`,
            `["TCP", "IPC"]`, `["tcp://*:5555", "IPC"]` or `["IPC", "INPROC"]`.

        forked: bool, Default `False`
            if `True`, the server is started in a separate thread and this method returns immediately.

        **kwargs:
            - context: `zmq.asyncio.Context`, optional,
                ZMQ context object to be used for creating sockets. If not supplied, a global shared context is used.
                For INPROC, either do not supply context or use the same context across all threads.
        """
        from ..server.server import parse_params, run

        servers = parse_params(self.id, [("ZMQ", dict(access_points=access_points, logger=self.logger, **kwargs))])

        for server in servers:
            server.add_thing(self)
        run(*servers, print_welcome_message=False)  # no welcome message for ZMQ

    @forkable  # noqa: F405
    def run_with_http_server(
        self,
        port: int = 8080,
        address: str = "0.0.0.0",  # SAST(id='hololinked.core.thing.Thing.run_with_http_server.address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
        # host: str = None,
        allowed_clients: str | list[str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        # protocol_version : int = 1,
        # network_interface : str = 'Ethernet',
        forked: bool = False,  # used by forkable decorator
        print_welcome_message: bool = True,
        **kwargs: dict[str, Any],
    ) -> None:
        """
        Quick-start to serve `Thing` over HTTP. This method is fully blocking, call `exit()` (`hololinked.server.exit()`)
        to unblock.

        Parameters
        ----------
        port: int
            the port at which the HTTP server should be run (unique)
        address: str
            A convenience option to set IP address apart from 0.0.0.0 (i.e. bind to all interfaces, which is default)
        ssl_context: ssl.SSLContext | None
            provide custom certificates with an SSL context for encrypted communication
        allowed_clients: str | list[str] | None
            serves request and sets CORS only from these clients, other clients are rejected with 403. Uses remote IP
            header value to achieve this. Unlike CORS, the server resource is not even executed if the client is not an allowed client.
            Note that the remote IP in a HTTP request is believable only from a trusted HTTP client, not a modified one.
        forked: bool, Default `False`
            if `True`, the server is started in a separate thread and this method returns immediately
        **kwargs: dict[str, Any]
            additional keyword arguments:

            - `property_handler`: `BaseHandler` | `PropertyHandler`,
                custom web request handler for property operations
            - `action_handler`: `BaseHandler` | `ActionHandler`,
                custom web request handler for action operations
            - `event_handler`: `BaseHandler` | `EventHandler`,
                custom event handler for handling events
        """
        from ..server import HTTPServer, run

        http_server = HTTPServer(
            port=port,
            address=address,
            logger=self.logger,
            ssl_context=ssl_context,
            allowed_clients=allowed_clients,
            **kwargs,
        )
        http_server.add_thing(self)
        run(http_server, print_welcome_message=print_welcome_message)

    @forkable  # noqa: F405
    def run(
        self,
        forked: bool = False,  # used by forkable decorator
        print_welcome_message: bool = True,
        **kwargs: dict[str, Any],
    ) -> None:
        """
        Expose the object with the given servers. This method is blocking until `exit()` (`hololinked.server.exit()`)
        is called.

        >>> Thing(id='example_id').run(servers=[http_server, zmq_server, mqtt_publisher])

        Parameters
        ----------
        forked: bool, Default `False`
            if `True`, the server is started in a separate thread and this method returns immediately.
        print_welcome_message: bool, Default `True`
            if `True`, a welcome message with server information is printed to the console.
        kwargs: dict[str, Any]
            keyword arguments

            - `access_points`: dict[str, dict | int | str | list[str]], optional
                The protocol name and its port or parameters to expose the object.
                for example - `[('HTTP', 9000), ('ZMQ', 'tcp://*:5555')]`

            - `servers`: list[BaseProtocolServer]
                list of instantiated servers to expose the object.
        """
        from ..server.server import BaseProtocolServer, parse_params, run  # noqa: F401

        access_points = kwargs.get("access_points", None)  # type: dict[str, dict | int | str | list[str]]
        servers = kwargs.get("servers", [])  # type: list[BaseProtocolServer] | None

        if access_points is None and len(servers) == 0:
            raise ValueError("At least one of access_points or servers must be provided.")
        if access_points is not None and len(servers) > 0:
            raise ValueError("Only one of access_points or servers can be provided.")

        if access_points is not None:
            servers = parse_params(self.id, access_points)
        for server in servers:
            server.add_thing(self)
        run(*servers, print_welcome_message=print_welcome_message)

    @action()
    def exit(self) -> None:
        """
        Stop serving the object. This method usually needs to be called remotely.
        The servers are not stopped, just the object run loop is exited.
        """
        if self.rpc_server is None:
            self.logger.debug("exit() called on a object that is not exposed yet.")
            return
        if self._owners:
            raise NotImplementedError(
                "call exit on the top-level object, composed objects cannot exit the loop. "
                + f"This object belongs to {self._owners.__class__.__name__} with ID {self._owners.id}."
            )
        self.rpc_server.stop()

    @action()
    def ping(self) -> None:
        """
        ping to see if it is alive. Successful when action succeeds with no return value and
        no timeout or exception raised on the client side.
        """
        pass

    def __hash__(self) -> int:
        filename = inspect.getfile(self.__class__)
        if filename is not None:
            # i.e. try to make it as unique as possible
            return hash(filename + self.__class__.__name__ + self.id)
        return hash(self.__class__.__name__ + self.id)

    def __eq__(self, other) -> bool:
        if not isinstance(other, Thing):
            return False
        return self.__class__ == other.__class__ and self.id == other.id

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.id})"

    def __contains__(self, item: Property | BoundAction | EventDispatcher) -> bool:
        return item in self.properties or item in self.actions or item in self.events

    def __enter__(self) -> "Thing":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        pass


from .state_machine import StateMachine  # noqa: F401, E402


__all__ = [Thing.__name__]
