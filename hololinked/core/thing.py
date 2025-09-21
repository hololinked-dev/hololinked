import logging
import inspect
import threading
import ssl
import typing
import warnings

from ..constants import ZMQ_TRANSPORTS
from ..utils import *  # noqa: F403
from ..exceptions import *  # noqa: F403
from ..serializers import Serializers, BaseSerializer, JSONSerializer
from ..server.server import BaseProtocolServer
from .properties import String, ClassSelector
from .property import Property
from .actions import BoundAction, action
from .events import EventDispatcher
from .meta import ThingMeta, Propertized, RemoteInvokable, EventSource


class Thing(Propertized, RemoteInvokable, EventSource, metaclass=ThingMeta):
    """
    Subclass from here to expose hardware or python objects on the network. Remotely accessible members of a `Thing` are
    segragated into properties, actions & events. Utilize properties for data that can be read and written,
    actions to instruct the object to perform tasks and events to get notified of any relevant information. State Machines
    can be used to contrain operations on properties and actions.

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

    logger = ClassSelector(
        class_=logging.Logger,
        default=None,
        allow_None=True,
        remote=False,
        doc="""logging.Logger instance to track log messages. Default logger with a IO-stream handler 
                    and network accessible handler is created if none supplied.""",
    )  # type: logging.Logger

    state_machine = None  # type: typing.Optional["StateMachine"]

    # remote properties
    state = String(
        default=None,
        allow_None=True,
        readonly=True,
        observable=True,
        fget=lambda self: self.state_machine.current_state if self.state_machine else None,
        doc="""current state machine's state if state machine present, `None` indicates absence of state machine.
                State machine returned state is always a string even if specified as an Enum in the state machine.""",
    )  # type: typing.Optional[str]

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
        logger: typing.Optional[logging.Logger] = None,
        serializer: typing.Optional[BaseSerializer | JSONSerializer] = None,
        **kwargs: typing.Dict[str, typing.Any],
    ) -> None:
        """
        Parameters
        ----------
        id: str
            String identifier of the instance. For an interconnected system of hardware,
            IDs are recommended to be unique. This value is used for many operations, for example -
            creating zmq socket address, tables in databases, and to identify the instance in a
            HTTP Server - (http(s)://{domain and sub domain}/{id}).
        logger: logging.Logger, optional
            logging.Logger instance to track log messages. Default logger with a IO-stream handler
            and network accessible handler is created if None supplied.
        serializer: BaseSerializer | JSONSerializer, optional
            Serializer to be used for serializing and deserializing data - preferred is a JSON Serializer.
            If not supplied, a `msgspec` based JSON Serializer is used.
        **kwargs: typing.Dict[str, Any]
            - remote_accessible_logger: `bool`, Default False.
                if False, network accessible handler is not attached to the logger. `remote_accessible_logger` can also be set as a
                class attribute.
            - use_default_db: `bool`, Default False.
                if True, default SQLite database is created where properties can be stored and loaded. There is no need to supply
                any database credentials. `use_default_db` value can also be set as a class attribute.
            - db_config_file: `str`, optional.
                if not using a default database, supply a JSON configuration file to create a database connection. Check documentaion
                of `hololinked.core.database`.
            - use_json_file: bool, Default False
                if True, a JSON file will be used as the property storage instead of a database. This value can also be
                set as a class attribute.
            - json_filename: str, optional
                If using JSON storage, this filename is used to persist property values. If not provided, a default filename
                is generated based on the instance name.
        """
        Propertized.__init__(self, id=id, logger=logger, **kwargs)
        RemoteInvokable.__init__(self)
        EventSource.__init__(self)
        if self.id.startswith("/"):
            self.id = self.id[1:]
            self.logger.info("removed leading '/' from id")
        if serializer is not None:
            Serializers.register_for_thing_instance(self.id, serializer)

        from .logger import prepare_object_logger
        from .state_machine import prepare_object_FSM
        from ..storage import prepare_object_storage

        prepare_object_logger(
            instance=self,
            log_level=kwargs.get("log_level", None),
            log_file=kwargs.get("log_file", None),
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
        from .zmq.rpc_server import RPCServer  # noqa: F401
        from ..server.zmq import ZMQServer  # noqa: F401
        from .logger import RemoteAccessHandler
        from ..storage.database import ThingDB

        # Type definitions
        self.rpc_server = None  # type: typing.Optional[RPCServer | ZMQServer]
        self.db_engine: typing.Optional[ThingDB]
        self._owners = None if not hasattr(self, "_owners") else self._owners  # type: typing.Optional[typing.List[Thing]]
        self._remote_access_loghandler: typing.Optional[RemoteAccessHandler]
        self._internal_fixed_attributes: typing.List[str]
        self._qualified_id: str
        self._state_machine_state: str
        # database operations
        self.properties.load_from_DB()
        # object is ready
        self.logger.info(f"initialialised Thing class {self.__class__.__name__} with id {self.id}")

    def __setattr__(self, __name: str, __value: typing.Any) -> None:
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
    def sub_things(self) -> typing.Dict[str, "Thing"]:
        """other `Thing`'s that are composed within this `Thing`."""
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
        ignore_errors: bool, optional, Default False
            if True, offending interaction affordances will be removed from the JSON.
            This is useful to build partial but always working ThingModel.
        skip_names: list[str], optional
            List of affordances names (of any type) to skip in the generated model.

        Returns
        -------
        hololinked.td.ThingModel
            represented as an object in python, gets automatically serialized to JSON when pushed out of the socket.
        """
        # allow_loose_schema: bool, optional, Default False
        #     Experimental properties, actions or events for which schema was not given will be supplied with a suitable
        #     value for node-wot to ignore validation or claim the accessed value for complaint with the schema.
        #     In other words, schema validation will always pass.
        from ..td.tm import ThingModel

        return ThingModel(instance=self, ignore_errors=ignore_errors, skip_names=skip_names).generate()

    thing_model = property(get_thing_model, doc=get_thing_model.__doc__)

    @forkable  # noqa: F405
    def run_with_zmq_server(
        self,
        access_points: list[ZMQ_TRANSPORTS] | ZMQ_TRANSPORTS | str | list[str] = ZMQ_TRANSPORTS.IPC,
        forked: bool = False,  # used by decorator
        # expose_eventloop : bool = False,
        **kwargs: typing.Dict[str, typing.Any],
    ) -> None:
        """
        Quick-start to serve `Thing` over ZMQ. This method is fully blocking. This
        method is blocking until `exit()` is called.

        Parameters
        ----------
        transports: Sequence[ZMQ_TRANSPORTS] | ZMQ_TRANSPORTS, Default ZMQ_TRANSPORTS.IPC or "IPC"
            ZMQ transport layers at which the object is exposed:

            - TCP -  custom implemented protocol in plain TCP - supply a socket address additionally or a random port
            will be automatically used.
            - IPC - inter process communication - connection can be made from other processes running
            locally within same computer. No client on the network will be able to contact the object using
            this transport. Beginners may use this transport for learning and testing without worrying about
            network security or technicalities of a sophisticated protocol like HTTP or MQTT. Also, use this transport
            if you wish to avoid configuring your firewall.
            - INPROC - one main python process spawns several threads in one of which the `Thing`
            will be running. The object can be contacted by a client on another thread but not from other processes
            or the network. One may use more than one form of transport.  All requests made will be anyway queued internally
            irrespective of origin.

            For multiple transports, supply a list of transports. For example: `[ZMQ_TRANSPORTS.TCP, ZMQ_TRANSPORTS.IPC]`,
            `["TCP", "IPC"]` or `["IPC", "INPROC"]`.

        **kwargs:
            - context: `zmq.asyncio.Context`, optional,
                ZMQ context object to be used for creating sockets. If not supplied, a new context is created.
                For INPROC clients, you need to provide the same context used here.
        """
        from .zmq.rpc_server import prepare_rpc_server

        prepare_rpc_server(instance=self, access_points=access_points, **kwargs)
        self.rpc_server.run()

    @forkable  # noqa: F405
    def run_with_http_server(
        self,
        port: int = 8080,
        address: str = "0.0.0.0",
        # host: str = None,
        allowed_clients: str | typing.Iterable[str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        # protocol_version : int = 1,
        # network_interface : str = 'Ethernet',
        forked: bool = False,  # used by forkable decorator
        **kwargs: typing.Dict[str, typing.Any],
    ) -> None:
        """
        Quick-start to serve `Thing` over HTTP. This method is fully blocking.

        Parameters
        ----------
        port: int
            the port at which the HTTP server should be run (unique)
        address: str
            A convenience option to set IP address apart from 0.0.0.0 (which is default)
        ssl_context: ssl.SSLContext | None
            use it for customized SSL context to provide encrypted communication. For certificate file and key file,
            one may also use `certfile` and `keyfile` options.
        allowed_clients: typing.Iterable[str] | str | None
            serves request and sets CORS only from these clients, other clients are rejected with 403. Uses remote IP
            header value to achieve this. Unlike CORS, the server resource is not even executed if the client is not an allowed client.
            Note that the remote IP in a HTTP request is believable only from a trusted HTTP client, not a modified one.
        **kwargs: typing.Dict[str, typing.Any]
            - certfile: `str`,
                alternative to SSL context, provide certificate file & key file to allow the server to create a SSL connection on its own
            - keyfile: `str`,
                alternative to SSL context, provide certificate file & key file to allow the server to create a SSL connection on its own
            - property_handler: `BaseHandler` | `PropertyHandler`,
                custom web request handler for property operations
            - action_handler: `BaseHandler` | `ActionHandler`,
                custom web request handler for action operations
            - event_handler: `BaseHandler` | `EventHandler`,
                custom event handler of your choice for handling events
        """
        # network_interface: str
        #     Currently there is no logic to detect the IP addresss (as externally visible) correctly, therefore please
        #     send the network interface name to retrieve the IP. If a DNS server is present, you may leave this field
        # host: str
        #     Host Server to subscribe to coordinate starting sequence of things & web GUI
        from ..server.http import HTTPServer

        self.run_with_zmq_server(transports=ZMQ_TRANSPORTS.INPROC, forked=True)
        http_server = HTTPServer(
            [],
            port=port,
            address=address,
            logger=self.logger,
            ssl_context=ssl_context,
            allowed_clients=allowed_clients,
            # network_interface=network_interface,
            **kwargs,
        )
        http_server.add_things(dict(INPROC=self.id))
        http_server.listen()

    @forkable  # noqa: F405
    def run(
        self,
        **kwargs: typing.Dict[str, typing.Any],
    ) -> None:
        """
        Expose the object with the given servers. This method is blocking until `exit()` is called.

        Parameters
        ----------
        servers: Sequence[BaseProtocolServer]
            list of instantiated servers to expose the object.
        """
        from ..server.http import HTTPServer
        from ..server.zmq import ZMQServer
        from .zmq.rpc_server import RPCServer, prepare_rpc_server

        access_points = kwargs.get("access_points", None)  # type: dict[str, dict | int | str | list[str]]
        servers = kwargs.get("servers", [])  # type: typing.Optional[typing.List[BaseProtocolServer]]

        if access_points is None and servers is None:
            raise ValueError("At least one of access_points or servers must be provided.")
        if access_points is not None and servers is not None:
            raise ValueError("Only one of access_points or servers can be provided.")

        if access_points is not None:
            for protocol, params in access_points:
                if protocol.upper() == "HTTP":
                    if isinstance(params, int):
                        params = dict(port=params)
                    http_server = HTTPServer([], **params)
                    servers.append(http_server)
                elif protocol.upper() == "ZMQ":
                    if isinstance(params, int):
                        params = dict(access_points=[f"tcp://*:{params}"])
                    elif isinstance(params, str):
                        params = dict(access_points=[params])
                    elif isinstance(params, list):
                        params = dict(access_points=params)
                    if not any(
                        isinstance(ap, str) and ap.upper().startswith("INPROC")
                        for ap in params.get("access_points", [])
                    ):
                        params["access_points"].append("INPROC")
                    prepare_rpc_server(self, **params)
                    servers.append(self.rpc_server)
                else:
                    warnings.warn(f"Unsupported protocol: {protocol}", category=UserWarning)

        if not any(isinstance(server, (RPCServer, ZMQServer)) for server in servers):
            prepare_rpc_server(self, access_points=ZMQ_TRANSPORTS.INPROC)
        for server in servers:
            # this cannot be merged with the loop below because self.rpc_server needs to be set first
            if isinstance(server, (RPCServer, ZMQServer)):
                self.rpc_server = server

        for server in servers:
            if isinstance(server, HTTPServer):

                def start_http_server(server: HTTPServer) -> None:
                    server.router.add_zmq_thing_instance(
                        server_id=self.rpc_server.id, thing_id=self.id, access_point="INPROC"
                    )
                    server.listen()

                threading.Thread(target=start_http_server, args=(server,)).start()
        self.rpc_server.run()

    @action()
    def exit(self) -> None:
        """Stop serving the object. This method can only be called remotely"""
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
        ping the `Thing` to see if it is alive. Ping successful when action succeeds with no return value and
        no timeout or exception raised on the client side.
        """
        pass

    def __hash__(self) -> int:
        filename = inspect.getfile(self.__class__)
        if filename is not None:
            return hash(filename + self.__class__.__name__ + self.id)
        return hash(self.__class__.__name__ + self.id)
        # i.e. unique to a computer

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
