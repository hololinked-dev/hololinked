import logging
import inspect
import os
import re
import ssl
import typing
import warnings
import zmq
import zmq.asyncio

from ..param.parameterized import Parameterized, ParameterizedMetaclass, edit_constant as edit_constant_parameters
from .constants import (JSON, LOGLEVEL, ZMQ_PROTOCOLS, HTTP_METHODS, JSONSerializable)
from .database import ThingDB, ThingInformation
from .serializers import _get_serializer_from_user_given_options, BaseSerializer, JSONSerializer
from .schema_validators import BaseSchemaValidator, JsonSchemaValidator
from .exceptions import BreakInnerLoop
from .action import action
from .dataklasses import HTTPResource, ZMQResource, build_our_temp_TD, get_organised_resources
from .utils import get_a_filename_from_instance, get_default_logger, getattr_without_descriptor_read
from .property import Property, ClassProperties
from .properties import String, ClassSelector, Selector, TypedKeyMappingsConstrainedDict
from .zmq_message_brokers import RPCServer, ServerTypes, EventPublisher
from .state_machine import StateMachine
from .events import Event
from .json_storage import ThingJsonStorage




class ThingMeta(ParameterizedMetaclass):
    """
    Metaclass for Thing, implements a ``__post_init__()`` call and instantiation of a container for properties' descriptor 
    objects. During instantiation of ``Thing``, first serializers, loggers and database connection are created, after which
    the user ``__init__`` is called. In ``__post_init__()``, that runs after user's ``__init__()``, the exposed resources 
    are segregated while accounting for any ``Event`` objects or instance specific properties created during init. Properties 
    are also loaded from database at this time. One can overload ``__post_init__()`` for any operations that rely on properties
    values loaded from database.
    """

    @classmethod
    def __prepare__(cls, name, bases):
        return TypedKeyMappingsConstrainedDict({},
            type_mapping = dict(
                state_machine = (StateMachine, type(None)),
                instance_name = String,
                log_level = Selector,
                logger = ClassSelector,
                logfile = String,
                db_config_file = String,
                object_info = Property, # it should not be set by the user
            ),
            allow_unspecified_keys = True
        )

    def __new__(cls, __name, __bases, __dict : TypedKeyMappingsConstrainedDict):
        return super().__new__(cls, __name, __bases, __dict._inner)

    def __call__(mcls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)

        instance.__post_init__()
        return instance

    def _create_param_container(mcs, mcs_members : dict) -> None:
        """
        creates ``ClassProperties`` instead of ``param``'s own ``Parameters`` 
        as the default container for descriptors. All properties have definitions 
        copied from ``param``.
        """
        mcs._param_container = ClassProperties(mcs, mcs_members)

    @property
    def properties(mcs) -> ClassProperties:
        """
        returns ``ClassProperties`` instance instead of ``param``'s own 
        ``Parameters`` instance. See code of ``param``.
        """
        return mcs._param_container



class Thing(Parameterized, metaclass=ThingMeta):
    """
    Subclass from here to expose python objects on the network (with HTTP/TCP) or to other processes (ZeroMQ)
    """

    __server_type__ = ServerTypes.THING # not a server, this needs to be removed.

    # local properties
    instance_name = String(default=None, regex=r'[A-Za-z]+[A-Za-z_0-9\-\/]*', constant=True, remote=False,
                        doc="""Unique string identifier of the instance. This value is used for many operations,
                        for example - creating zmq socket address, tables in databases, and to identify the instance 
                        in the HTTP Server - (http(s)://{domain and sub domain}/{instance name}). 
                        If creating a big system, instance names are recommended to be unique.""") # type: str
    logger = ClassSelector(class_=logging.Logger, default=None, allow_None=True, remote=False,
                        doc="""logging.Logger instance to print log messages. Default 
                            logger with a IO-stream handler and network accessible handler is created 
                            if none supplied.""") # type: logging.Logger
    zmq_serializer = ClassSelector(class_=(BaseSerializer, str),
                        allow_None=True, default='json', remote=False,
                        doc="""Serializer used for exchanging messages with python RPC clients. Subclass the base serializer 
                        or one of the available serializers to implement your own serialization requirements; or, register 
                        type replacements. Default is JSON. Some serializers like MessagePack improve performance many times 
                        compared to JSON and can be useful for data intensive applications within python.""") # type: BaseSerializer
    http_serializer = ClassSelector(class_=(JSONSerializer, str), default=None, allow_None=True, remote=False,
                        doc="""Serializer used for exchanging messages with a HTTP clients,
                            subclass JSONSerializer to implement your own JSON serialization requirements; or, 
                            register type replacements. Other types of serializers are currently not allowed for HTTP clients.""") # type: JSONSerializer
    schema_validator = ClassSelector(class_=BaseSchemaValidator, default=JsonSchemaValidator, allow_None=True,
                        remote=False, isinstance=False,
                        doc="""Validator for JSON schema. If not supplied, a default JSON schema validator is created.""") # type: BaseSchemaValidator

    # remote properties
    state = String(default=None, allow_None=True, URL_path='/state', readonly=True, observable=True,
                fget=lambda self : self.state_machine.current_state if hasattr(self, 'state_machine') else None,
                doc="current state machine's state if state machine present, None indicates absence of state machine.") #type: typing.Optional[str]
    httpserver_resources = Property(readonly=True, URL_path='/resources/http-server',
                        doc="object's resources exposed to HTTP client (through ``hololinked.server.HTTPServer.HTTPServer``)",
                        fget=lambda self: self._httpserver_resources ) # type: typing.Dict[str, HTTPResource]
    zmq_resources = Property(readonly=True, URL_path='/resources/zmq-object-proxy',
                        doc="object's resources exposed to RPC client, similar to HTTP resources but differs in details.",
                        fget=lambda self: self._zmq_resources) # type: typing.Dict[str, ZMQResource]
    gui_resources = Property(readonly=True, URL_path='/resources/portal-app',
                        doc="""object's data read by hololinked-portal GUI client, similar to http_resources but differs 
                        in details.""",
                        fget=lambda self: build_our_temp_TD(self)) # type: typing.Dict[str, typing.Any]
    GUI = Property(default=None, allow_None=True, URL_path='/resources/web-gui', fget = lambda self : self._gui,
                        doc="GUI specified here will become visible at GUI tab of hololinked-portal dashboard tool")
    object_info = Property(doc="contains information about this object like the class name, script location etc.",
                        URL_path='/object-info') # type: ThingInformation


    def __init__(self, *, instance_name : str, logger : typing.Optional[logging.Logger] = None,
                serializer : typing.Optional[JSONSerializer] = None, **kwargs) -> None:
        """
        Parameters
        ----------
        instance_name: str
            Unique string identifier of the instance. This value is used for many operations,
            for example - creating zmq socket address, tables in databases, and to identify the instance in the HTTP Server - 
            (http(s)://{domain and sub domain}/{instance name}). 
            If creating a big system, instance names are recommended to be unique.
        logger: logging.Logger, optional
            logging.Logger instance to print log messages. Default logger with a IO-stream handler and network 
            accessible handler is created if none supplied.
        serializer: JSONSerializer, optional
            custom JSON serializer. To use separate serializer for python RPC clients and cross-platform 
            HTTP clients, use keyword arguments zmq_serializer and http_serializer and leave this argument at None.
        **kwargs:
            zmq_serializer: BaseSerializer | str, optional 
                Serializer used for exchanging messages with python RPC clients. If string value is supplied, 
                supported are 'msgpack', 'pickle', 'serpent', 'json'. Subclass the base serializer 
                ``hololinked.server.serializer.BaseSerializer`` or one of the available serializers to implement your 
                own serialization requirements; or, register type replacements. Default is JSON. Some serializers like 
                MessagePack improve performance many times  compared to JSON and can be useful for data intensive 
                applications within python. The serializer supplied here must also be supplied to object proxy from 
                ``hololinked.client``. 
            http_serializer: JSONSerializer, optional
                serializer used for cross platform HTTP clients. 
            use_default_db: bool, Default False
                if True, default SQLite database is created where properties can be stored and loaded. There is no need to supply
                any database credentials. This value can also be set as a class attribute, see docs.
            logger_remote_access: bool, Default True
                if False, network accessible handler is not attached to the logger. This value can also be set as a 
                class attribute, see docs.
            schema_validator: BaseSchemaValidator, optional
                schema validator class for JSON schema validation, not supported by ZMQ clients. 
            db_config_file: str, optional
                if not using a default database, supply a JSON configuration file to create a connection. Check documentaion
                of ``hololinked.server.database``.
            use_json_file: bool, Default False
                if True, a JSON file will be used as the property storage instead of a database. This value can also be
                set as a class attribute.
            json_filename: str, optional
                If using JSON storage, this filename is used to persist property values. If not provided, a default filename
                is generated based on the instance name.

        """
        if instance_name.startswith('/'):
            instance_name = instance_name[1:]
        # Type definitions
        self._owner : typing.Optional[Thing] = None
        self._internal_fixed_attributes : typing.List[str]
        self._full_URL_path_prefix : str
        self._gui = None # filler for a future feature
        self._event_publisher = None # type : typing.Optional[EventPublisher]
        self.rpc_server  = None # type: typing.Optional[RPCServer]
        self.message_broker = None # type : typing.Optional[AsyncPollingZMQServer]
        # serializer
        if not isinstance(serializer, JSONSerializer) and serializer != 'json' and serializer is not None:
            raise TypeError("serializer key word argument must be JSONSerializer. If one wishes to use separate serializers " +
                            "for python clients and HTTP clients, use zmq_serializer and http_serializer keyword arguments.")
        zmq_serializer = serializer or kwargs.pop('zmq_serializer', 'json')
        http_serializer = serializer if isinstance(serializer, JSONSerializer) else kwargs.pop('http_serializer', 'json')
        zmq_serializer, http_serializer = _get_serializer_from_user_given_options(
                                                                    zmq_serializer=zmq_serializer,
                                                                    http_serializer=http_serializer
                                                                )
        super().__init__(instance_name=instance_name, logger=logger,
                        zmq_serializer=zmq_serializer, http_serializer=http_serializer, **kwargs)

        self._prepare_logger(
                    log_level=kwargs.get('log_level', None),
                    log_file=kwargs.get('log_file', None),
                    remote_access=kwargs.get('logger_remote_access', self.__class__.logger_remote_access if hasattr(
                                                                self.__class__, 'logger_remote_access') else False)
                )
        self._prepare_state_machine()

        # choose storage type, if use_json_file is True - use JSON storage, else - use database
        if kwargs.get('use_json_file',
                      self.__class__.use_json_file if hasattr(self.__class__, 'use_json_file') else False):
            self._prepare_json_storage(filename=kwargs.get('json_filename', f"{get_a_filename_from_instance(self, 'json')}"))
        else:
            self._prepare_DB(kwargs.get('use_default_db', False), kwargs.get('db_config_file', None))


    def __post_init__(self):
        self._prepare_resources()
        self.load_properties_from_DB()
        self.logger.info(f"initialialised Thing class {self.__class__.__name__} with instance name {self.instance_name}")


    def _prepare_resources(self):
        """
        this method analyses the members of the class which have '_remote_info' variable declared
        and extracts information necessary to make RPC functionality work.
        """
        # The following dict is to be given to the HTTP server
        self._zmq_resources, self._httpserver_resources, self.instance_resources = get_organised_resources(self)


    def _prepare_logger(self, log_level : int, log_file : str, remote_access : bool = False):
        from .logger import RemoteAccessHandler
        if self.logger is None:
            self.logger = get_default_logger(self.instance_name,
                                    logging.INFO if not log_level else log_level,
                                    None if not log_file else log_file)
        if remote_access:
            if not any(isinstance(handler, RemoteAccessHandler) for handler in self.logger.handlers):
                self._remote_access_loghandler = RemoteAccessHandler(instance_name='logger',
                                                    maxlen=500, emit_interval=1, logger=self.logger)
                                                    # thing has its own logger so we dont recreate one for
                                                    # remote access handler
                self.logger.addHandler(self._remote_access_loghandler)

        if not isinstance(self, logging.Logger):
            for handler in self.logger.handlers:
                # if remote access is True or not, if a default handler is found make a variable for it anyway
                if isinstance(handler, RemoteAccessHandler):
                    self._remote_access_loghandler = handler


    def _prepare_state_machine(self):
        if hasattr(self, 'state_machine'):
            self.state_machine._prepare(self)
            self.logger.debug("setup state machine")


    def _prepare_DB(self, default_db : bool = False, config_file : str = None):
        if not default_db and not config_file:
            self.object_info
            return
        # 1. create engine
        self.db_engine = ThingDB(instance=self, config_file=None if default_db else config_file,
                                    serializer=self.zmq_serializer) # type: ThingDB
        # 2. create an object metadata to be used by different types of clients
        object_info = self.db_engine.fetch_own_info()
        if object_info is not None:
            self._object_info = object_info
        # 3. enter properties to DB if not already present 
        if self.object_info.class_name != self.__class__.__name__:
            raise ValueError("Fetched instance name and class name from database not matching with the ",
                "current Thing class/subclass. You might be reusing an instance name of another subclass ",
                "and did not remove the old data from database. Please clean the database using database tools to ",
                "start fresh.")

    def _prepare_json_storage(self, filename: str = None):
        if not filename:
            filename = f"{get_a_filename_from_instance(self, 'json')}"
        self.db_engine = ThingJsonStorage(filename=filename, instance=self)

 
    @object_info.getter
    def _get_object_info(self):
        if not hasattr(self, '_object_info'):
            self._object_info = ThingInformation(
                    instance_name  = self.instance_name,
                    class_name     = self.__class__.__name__,
                    script         = os.path.dirname(os.path.abspath(inspect.getfile(self.__class__))),
                    http_server    = "USER_MANAGED",
                    kwargs         = "USER_MANAGED",
                    eventloop_instance_name = "USER_MANAGED",
                    level          = "USER_MANAGED",
                    level_type     = "USER_MANAGED"
                )
        return self._object_info

    @object_info.setter
    def _set_object_info(self, value):
        self._object_info = ThingInformation(**value)
        for name, thing in inspect._getmembers(self, lambda o: isinstance(o, Thing), getattr_without_descriptor_read):
            thing._object_info.http_server = self._object_info.http_server


    @property
    def properties(self) -> ClassProperties:
        """container for the property descriptors of the object."""
        return self.parameters

    @action(URL_path='/properties', http_method=HTTP_METHODS.GET)
    def _get_properties(self, **kwargs) -> typing.Dict[str, typing.Any]:
        """
        """
        skip_props = ["httpserver_resources", "zmq_resources", "gui_resources", "GUI", "object_info"]
        for prop_name in skip_props:
            if prop_name in kwargs:
                raise RuntimeError("GUI, httpserver resources, RPC resources , object info etc. cannot be queried" +
                                  " using multiple property fetch.")
        data = {}
        if len(kwargs) == 0:
            for name, prop in self.properties.descriptors.items():
                if name in skip_props or not isinstance(prop, Property):
                    continue
                if prop._remote_info is None:
                    continue
                data[name] = prop.__get__(self, type(self))
        elif 'names' in kwargs:
            names = kwargs.get('names')
            if not isinstance(names, (list, tuple, str)):
                raise TypeError(f"Specify properties to be fetched as a list, tuple or comma separated names. Givent type {type(names)}")
            if isinstance(names, str):
                names = names.split(',')
            for requested_prop in names:
                if not isinstance(requested_prop, str):
                    raise TypeError(f"property name must be a string. Given type {type(requested_prop)}")
                if not isinstance(self.properties[requested_prop], Property) or self.properties[requested_prop]._remote_info is None:
                    raise AttributeError("this property is not remote accessible")
                data[requested_prop] = self.properties[requested_prop].__get__(self, type(self))
        elif len(kwargs.keys()) != 0:
            for rename, requested_prop in kwargs.items():
                if not isinstance(self.properties[requested_prop], Property) or self.properties[requested_prop]._remote_info is None:
                    raise AttributeError("this property is not remote accessible")
                data[rename] = self.properties[requested_prop].__get__(self, type(self))
        return data

    @action(URL_path='/properties', http_method=[HTTP_METHODS.PUT, HTTP_METHODS.PATCH])
    def _set_properties(self, **values : typing.Dict[str, typing.Any]) -> None:
        """ 
        set properties whose name is specified by keys of a dictionary
        
        Parameters
        ----------
        values: Dict[str, Any]
            dictionary of property names and its values
        """
        produced_error = False
        errors = ''
        for name, value in values.items():
            try:
                setattr(self, name, value)
            except Exception as ex:
                self.logger.error(f"could not set attribute {name} due to error {str(ex)}")
                errors += f'{name} : {str(ex)}\n'
                produced_error = True
        if produced_error:
            ex = RuntimeError("Some properties could not be set due to errors. " +
                            "Check exception notes or server logs for more information.")
            ex.__notes__ = errors
            raise ex from None

    @action(URL_path='/properties/db', http_method=HTTP_METHODS.GET)
    def _get_properties_in_db(self) -> typing.Dict[str, JSONSerializable]:
        """
        get all properties in the database
        
        Returns
        -------
        Dict[str, JSONSerializable]
            dictionary of property names and their values
        """
        if not hasattr(self, 'db_engine'):
            return {}
        props = self.db_engine.get_all_properties()
        final_list = {}
        for name, prop in props.items():
            try:
                self.http_serializer.dumps(prop)
                final_list[name] = prop
            except Exception as ex:
                self.logger.error(f"could not serialize property {name} to JSON due to error {str(ex)}, skipping this property")
        return final_list

    @action(URL_path='/properties', http_method=HTTP_METHODS.POST)
    def _add_property(self, name : str, prop : JSON) -> None:
        """
        add a property to the object
        
        Parameters
        ----------
        name: str
            name of the property
        prop: Property
            property object
        """
        raise NotImplementedError("this method will be implemented properly in a future release")
        prop = Property(**prop)
        self.properties.add(name, prop)
        self._prepare_resources()
        # instruct the clients to fetch the new resources

    @property
    def event_publisher(self) -> EventPublisher:
        """
        event publishing PUB socket owning object, valid only after 
        ``run()`` is called, otherwise raises AttributeError.
        """
        return self._event_publisher

    @event_publisher.setter
    def event_publisher(self, value : EventPublisher) -> None:
        if self._event_publisher is not None:
            if value is not self._event_publisher:
                raise AttributeError("Can set event publisher only once")

        def recusively_set_event_publisher(obj : Thing, publisher : EventPublisher) -> None:
            for name, evt in inspect._getmembers(obj, lambda o: isinstance(o, Event), getattr_without_descriptor_read):
                assert isinstance(evt, Event), "object is not an event"
                # above is type definition
                e = evt.__get__(obj, type(obj))
                e.publisher = publisher
                e._remote_info.socket_address = publisher.socket_address
                self.logger.info(f"registered event '{evt.friendly_name}' serving at PUB socket with address : {publisher.socket_address}")
            for name, subobj in inspect._getmembers(obj, lambda o: isinstance(o, Thing), getattr_without_descriptor_read):
                if name == '_owner':
                    continue
                recusively_set_event_publisher(subobj, publisher)
            obj._event_publisher = publisher

        recusively_set_event_publisher(self, value)


    @action(URL_path='/properties/db-reload', http_method=HTTP_METHODS.POST)
    def load_properties_from_DB(self):
        """
        Load and apply property values which have ``db_init`` or ``db_persist``
        set to ``True`` from database
        """
        if not hasattr(self, 'db_engine'):
            return
        missing_properties = self.db_engine.create_missing_properties(self.__class__.properties.db_init_objects,
                                                                    get_missing_property_names=True)
        # 4. read db_init and db_persist objects
        with edit_constant_parameters(self):
            for db_prop, value in self.db_engine.get_all_properties().items():
                try:
                    prop_desc = self.properties.descriptors[db_prop]
                    if (prop_desc.db_init or prop_desc.db_persist) and db_prop not in missing_properties:
                        setattr(self, db_prop, value) # type: ignore
                except Exception as ex:
                    self.logger.error(f"could not set attribute {db_prop} due to error {str(ex)}")


    @action(URL_path='/resources/postman-collection', http_method=HTTP_METHODS.GET)
    def get_postman_collection(self, domain_prefix : str = None):
        """
        organised postman collection for this object
        """
        from .api_platforms import postman_collection
        return postman_collection.build(instance=self,
                    domain_prefix=domain_prefix if domain_prefix is not None else self._object_info.http_server)


    @action(URL_path='/resources/wot-td', http_method=HTTP_METHODS.GET)
    def get_thing_description(self, authority : typing.Optional[str] = None, ignore_errors : bool = False):
                            # allow_loose_schema : typing.Optional[bool] = False):
        """
        generate thing description schema of Web of Things https://www.w3.org/TR/wot-thing-description11/.
        one can use the node-wot as a client for the object with the generated schema 
        (https://github.com/eclipse-thingweb/node-wot). Other WoT related tools based on TD will be compatible. 
        Composed Things that are not the top level object is currently not supported.
        
        Parameters
        ----------
        authority: str, optional
            protocol with DNS or protocol with hostname+port, for example 'https://my-pc:8080' or 
            'http://my-pc:9090' or 'https://IT-given-domain-name'. If absent, a value will be automatically
            given using ``socket.gethostname()`` and the port at which the last HTTPServer (``hololinked.server.HTTPServer``) 
            attached to this object was running.
        ignore_errors: bool, optional, Default False
            if True, offending interaction affordances will be removed from the schema. This is useful to build partial but working
            schema always.             
        Returns
        -------
        hololinked.wot.td.ThingDescription
            represented as an object in python, gets automatically serialized to JSON when pushed out of the socket. 
        """
        # allow_loose_schema: bool, optional, Default False 
        #     Experimental properties, actions or events for which schema was not given will be supplied with a suitable 
        #     value for node-wot to ignore validation or claim the accessed value for complaint with the schema.
        #     In other words, schema validation will always pass.  
        from .td import ThingDescription
        return ThingDescription(instance=self, authority=authority or self._object_info.http_server,
                                    allow_loose_schema=False, ignore_errors=ignore_errors).produce() #allow_loose_schema)


    @action(URL_path='/exit', http_method=HTTP_METHODS.POST)
    def exit(self) -> None:
        """
        Exit the object without killing the eventloop that runs this object. If Thing was 
        started using the run() method, the eventloop is also killed. This method can
        only be called remotely.
        """
        if self.rpc_server is None:
            return
        if self._owner is None:
            self.rpc_server.stop_polling()
            raise BreakInnerLoop # stops the inner loop of the object
        else:
            warnings.warn("call exit on the top object, composed objects cannot exit the loop.", RuntimeWarning)

    @action()
    def ping(self) -> None:
        """ping the Thing to see if it is alive"""
        pass

    def run(self,
            zmq_protocols : typing.Union[typing.Sequence[ZMQ_PROTOCOLS],
                                         ZMQ_PROTOCOLS] = ZMQ_PROTOCOLS.IPC,
            # expose_eventloop : bool = False,
            **kwargs
        ) -> None:
        """
        Quick-start ``Thing`` server by creating a default eventloop & ZMQ servers. This 
        method is blocking until exit() is called.

        Parameters
        ----------
        zmq_protocols: Sequence[ZMQ_PROTOCOLS] | ZMQ_Protocools, Default ZMQ_PROTOCOLS.IPC or "IPC"
            zmq transport layers at which the object is exposed. 
            TCP - provides network access apart from HTTP - please supply a socket address additionally.  
            IPC - inter process communication - connection can be made from other processes running 
            locally within same computer. No client on the network will be able to contact the object using
            this transport. INPROC - one main python process spawns several threads in one of which the ``Thing``
            the running. The object can be contacted by a client on another thread but neither from other processes 
            or the network. One may use more than one form of transport.  All requests made will be anyway queued internally
            irrespective of origin. 
        
        **kwargs
            tcp_socket_address: str, optional
                socket_address for TCP access, for example: tcp://0.0.0.0:61234
            context: zmq.asyncio.Context, optional
                zmq context to be used. If not supplied, a new context is created.
                For INPROC clients, you need to provide a context.
        """
        # expose_eventloop: bool, False
        #     expose the associated Eventloop which executes the object. This is generally useful for remotely 
        #     adding more objects to the same event loop.
        # dont specify http server as a kwarg, as the other method run_with_http_server has to be used
        self._prepare_resources()
        context = kwargs.get('context', None)
        if context is not None and not isinstance(context, zmq.asyncio.Context):
            raise TypeError("context must be an instance of zmq.asyncio.Context")
        context = context or zmq.asyncio.Context()

        self.rpc_server = RPCServer(
                                instance_name=self.instance_name,
                                server_type=self.__server_type__.value,
                                context=context,
                                protocols=zmq_protocols,
                                zmq_serializer=self.zmq_serializer,
                                http_serializer=self.http_serializer,
                                tcp_socket_address=kwargs.get('tcp_socket_address', None),
                                logger=self.logger
                            )
        self.message_broker = self.rpc_server.inner_inproc_server
        self.event_publisher = self.rpc_server.event_publisher

        from .eventloop import EventLoop
        self.event_loop = EventLoop(
                    instance_name=f'{self.instance_name}/eventloop',
                    things=[self],
                    logger=self.logger,
                    zmq_serializer=self.zmq_serializer,
                    http_serializer=self.http_serializer,
                    expose=False, # expose_eventloop
                )

        if kwargs.get('http_server', None):
            from .HTTPServer import HTTPServer
            httpserver = kwargs.pop('http_server')
            assert isinstance(httpserver, HTTPServer)
            httpserver._zmq_protocol = ZMQ_PROTOCOLS.INPROC
            httpserver._zmq_inproc_socket_context = context
            httpserver._zmq_inproc_event_context = self.event_publisher.context
            assert httpserver.all_ok
            httpserver.tornado_instance.listen(port=httpserver.port, address=httpserver.address)
        self.event_loop.run()


    def run_with_http_server(self, port : int = 8080, address : str = '0.0.0.0',
                # host : str = None,
                allowed_clients : typing.Union[str, typing.Iterable[str]] = None,
                ssl_context : ssl.SSLContext = None, # protocol_version : int = 1,
                # network_interface : str = 'Ethernet',
                **kwargs):
        """
        Quick-start ``Thing`` server by creating a default eventloop & servers. This 
        method is fully blocking.

        Parameters
        ----------
        port: int
            the port at which the HTTP server should be run (unique)
        address: str
            set custom IP address, default is localhost (0.0.0.0)
        ssl_context: ssl.SSLContext | None
            use it for highly customized SSL context to provide encrypted communication
        allowed_clients
            serves request and sets CORS only from these clients, other clients are rejected with 403. Unlike pure CORS
            feature, the server resource is not even executed if the client is not an allowed client.
        **kwargs,
            certfile: str
                alternative to SSL context, provide certificate file & key file to allow the server to create a SSL connection on its own
            keyfile: str
                alternative to SSL context, provide certificate file & key file to allow the server to create a SSL connection on its own
            request_handler: RPCHandler
                custom web request handler of your choice
            event_handler: BaseHandler | EventHandler
                custom event handler of your choice for handling events
        """
        # network_interface: str
        #     Currently there is no logic to detect the IP addresss (as externally visible) correctly, therefore please 
        #     send the network interface name to retrieve the IP. If a DNS server is present, you may leave this field
        # host: str
        #     Host Server to subscribe to coordinate starting sequence of things & web GUI

        from .HTTPServer import HTTPServer

        http_server = HTTPServer(
            [self.instance_name], logger=self.logger, serializer=self.http_serializer,
            port=port, address=address, ssl_context=ssl_context,
            allowed_clients=allowed_clients, schema_validator=self.schema_validator,
            # network_interface=network_interface, 
            **kwargs,
        )

        self.run(
            zmq_protocols=ZMQ_PROTOCOLS.INPROC,
            http_server=http_server,
            context=kwargs.get('context', None)
        ) # blocks until exit is called

        http_server.tornado_instance.stop()




