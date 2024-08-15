import typing 
import threading
import jsonschema

from ..param.parameterized import Parameterized, ParameterizedMetaclass
from .constants import JSON 
from .utils import pep8_to_URL_path
from .config import global_config
from .zmq_message_brokers import EventPublisher
from .dataklasses import ServerSentEvent
from .security_definitions import BaseSecurityDefinition



class Event:
    """
    Asynchronously push arbitrary messages to clients. Apart from default events created by the package (like state
    change event, observable properties etc.), events are supposed to be created at class level or at ``__init__`` 
    as a instance attribute, otherwise their publishing socket is unbound and will lead to ``AttributeError``.  

    Parameters
    ----------
    name: str
        name of the event, specified name may contain dashes and can be used on client side to subscribe to this event.
    URL_path: str
        URL path of the event if a HTTP server is used. only GET HTTP methods are supported. 
    doc: str
        docstring for the event
    schema: JSON
        schema of the event, if the event is JSON complaint. HTTP clients can validate the data with this schema. There
        is no validation on server side.
    """
    # security: Any
    #     security necessary to access this event.

    __slots__ = ['friendly_name', '_internal_name', '_obj_name',
                'doc', 'schema', 'URL_path', 'security', 'label', 'owner']


    def __init__(self, friendly_name : str, URL_path : typing.Optional[str] = None, doc : typing.Optional[str] = None, 
                schema : typing.Optional[JSON] = None, # security : typing.Optional[BaseSecurityDefinition] = None,
                label : typing.Optional[str] = None) -> None:
        self.friendly_name = friendly_name 
        self.doc = doc 
        if global_config.validate_schemas and schema:
            jsonschema.Draft7Validator.check_schema(schema)
        self.schema = schema
        self.URL_path = URL_path or f'/{pep8_to_URL_path(friendly_name)}'
        # self.security = security
        self.label = label
       

    def __set_name__(self, owner : ParameterizedMetaclass, name : str) -> None:
        self._internal_name = f"{pep8_to_URL_path(name)}-dispatcher"
        self._obj_name = name
        self.owner = owner

    @typing.overload
    def __get__(self, obj, objtype) -> "EventDispatcher":
        ...

    def __get__(self, obj : ParameterizedMetaclass, objtype : typing.Optional[type] = None):
        try:
            if not obj:
                return self
            return obj.__dict__[self._internal_name]
        except KeyError:
            raise AttributeError("Event object not yet initialized, please dont access now." +
                                " Access after Thing is running.")
        
    def __set__(self, obj : Parameterized, value : typing.Any) -> None:
        if isinstance(value, EventDispatcher):
            value._remote_info.name = self.friendly_name
            value._remote_info.obj_name = self._obj_name
            value._owner_inst = obj
            current_obj = obj.__dict__.get(self._internal_name, None) # type: typing.Optional[EventDispatcher]
            if current_obj and current_obj._publisher:
                current_obj._publisher.unregister(current_obj)
            obj.__dict__[self._internal_name] = value 
        else:
            raise TypeError(f"Supply EventDispatcher object to event {self._obj_name}, not type {type(value)}.")

    

class EventDispatcher:
    """
    The actual worker which pushes the event. The separation is necessary between ``Event`` and 
    ``EventDispatcher`` to allow class level definitions of the ``Event`` 
    """
    def __init__(self, unique_identifier : str) -> None:
        self._unique_identifier = bytes(unique_identifier, encoding='utf-8')   
        self._unique_zmq_identifier = self._unique_identifier
        self._unique_http_identifier = self._unique_identifier      
        self._publisher = None
        self._remote_info = ServerSentEvent(unique_identifier=unique_identifier)
        self._owner_inst = None

    @property
    def publisher(self) -> "EventPublisher": 
        """
        Event publishing PUB socket owning object.
        """
        return self._publisher
    
    @publisher.setter
    def publisher(self, value : "EventPublisher") -> None:
        if not self._publisher:
            self._publisher = value
            self._publisher.register(self)
        else:
            raise AttributeError("cannot reassign publisher attribute of event {}".format(self.name)) 

    def push(self, data : typing.Any = None, *, serialize : bool = True, **kwargs) -> None:
        """
        publish the event. 

        Parameters
        ----------
        data: Any
            payload of the event
        serialize: bool, default True
            serialize the payload before pushing, set to False when supplying raw bytes. 
        **kwargs:
            zmq_clients: bool, default True
                pushes event to RPC clients, irrelevant if ``Thing`` uses only one type of serializer (refer to 
                difference between zmq_serializer and http_serializer).
            http_clients: bool, default True
                pushed event to HTTP clients, irrelevant if ``Thing`` uses only one type of serializer (refer to 
                difference between zmq_serializer and http_serializer).
        """
        self.publisher.publish(self, data, zmq_clients=kwargs.get('zmq_clients', True), 
                                http_clients=kwargs.get('http_clients', True), serialize=serialize)




class CriticalEvent(Event):
    """
    Push events to client and get acknowledgement for that
    """

    def __init__(self, name : str, URL_path : typing.Optional[str] = None) -> None:
        super().__init__(name, URL_path)
        self._synchronize_event = threading.Event()

    def receive_acknowledgement(self, timeout : typing.Union[float, int, None]) -> bool:
        """
        Receive acknowlegement for event receive. When the timeout argument is present and not None, 
        it should be a floating point number specifying a timeout for the operation in seconds (or fractions thereof).
        """
        return self._synchronize_event.wait(timeout=timeout)

    def _set_acknowledgement(self):
        """
        Method to be called by RPC server when an acknowledgement is received. Not for user to be set.
        """
        self._synchronize_event.set()


__all__ = [
    Event.__name__,
]