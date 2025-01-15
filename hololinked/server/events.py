import inspect
import typing 
import threading
import jsonschema

from ..param.parameterized import Parameterized, ParameterizedMetaclass
from ..constants import JSON 
from ..utils import getattr_without_descriptor_read, pep8_to_dashed_name
from ..config import global_config




class Event:
    """
    Asynchronously push arbitrary messages to clients. Apart from default events created by the package (like state
    change event, observable properties etc.), events are supposed to be created at class level or at ``__init__`` 
    as a instance attribute, otherwise their publishing socket is unbound and will lead to ``AttributeError``.  

    Parameters
    ----------
    name: str
        name of the event, specified name may contain dashes and can be used on client side to subscribe to this event.
    doc: str
        docstring for the event
    schema: JSON
        schema of the event, if the event is JSON complaint. HTTP clients can validate the data with this schema. There
        is no validation on server side.
    """
    # security: Any
    #     security necessary to access this event.

    __slots__ = ['friendly_name', 'name', '_internal_name', '_publisher', '_observable',
                'doc', 'schema', 'security', 'label', 'owner']


    def __init__(self, friendly_name : str, doc : typing.Optional[str] = None, 
                schema : typing.Optional[JSON] = None, # security : typing.Optional[BaseSecurityDefinition] = None,
                label : typing.Optional[str] = None) -> None:
        self.friendly_name = friendly_name 
        self.doc = doc 
        if global_config.validate_schemas and schema:
            jsonschema.Draft7Validator.check_schema(schema)
        self.schema = schema
        # self.security = security
        self.label = label
        self._publisher = None # type: typing.Optional["EventPublisher"]
        self._observable = False
       
    def __set_name__(self, owner : ParameterizedMetaclass, name : str) -> None:
        self._internal_name = f"{pep8_to_dashed_name(name)}-dispatcher"
        self.name = name
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
            if not obj.__dict__.get(self._internal_name, None):
                value._owner_inst = obj
                obj.__dict__[self._internal_name] = value 
            else:
                raise AttributeError(f"Event object already assigned for {self.name}. Cannot reassign.") 
                # may be allowing to reassign is not a bad idea 
        else:
            raise TypeError(f"Supply EventDispatcher object to event {self.name}, not type {type(value)}.")

    

class EventDispatcher:
    """
    The actual worker which pushes the event. The separation is necessary between ``Event`` and 
    ``EventDispatcher`` to allow class level definitions of the ``Event`` 
    """

    __slots__ = ['_unique_identifier', '_unique_zmq_identifier', '_unique_http_identifier', '_publisher', '_owner_inst']

    def __init__(self, unique_identifier : str, publisher : "EventPublisher") -> None:
        self._unique_identifier = bytes(unique_identifier, encoding='utf-8')   
        self._unique_zmq_identifier = self._unique_identifier
        self._unique_http_identifier = self._unique_identifier      
        self._publisher = None
        self._owner_inst = None
        self.publisher = publisher

    
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
        elif value != self._publisher:
            raise AttributeError("cannot reassign publisher attribute of event {}".format(self._unique_identifier)) 

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


    def receive_acknowledgement(self, timeout : typing.Union[float, int, None]) -> bool:
        """
        Receive acknowlegement for event receive. When the timeout argument is present and not None, 
        it should be a floating point number specifying a timeout for the operation in seconds (or fractions thereof).
        """
        return self._synchronize_event.wait(timeout=timeout)

    def _set_acknowledgement(self, *args, **kwargs) -> None:
        """
        Method to be called by RPC server when an acknowledgement is received. Not for user to be set.
        """
        self._synchronize_event.set()
        




class EventSource:
    """Class to add event functionality to the object"""

    id : str

    def __init__(self) -> None:
          self._event_publisher = None # type : typing.Optional["EventPublisher"]
      
    @property
    def change_events(self) -> typing.Dict[str, Event]:
        try:
            return getattr(self, f'_{self.id}_change_events')
        except AttributeError:
            change_events = dict()
            for name, evt in inspect._getmembers(self, lambda o: isinstance(o, Event), getattr_without_descriptor_read):
                assert isinstance(evt, Event), "object is not an event"
                if not evt._observable:
                    continue
                change_events[name] = evt
            setattr(self, f'_{self.id}_change_events', change_events)
            return change_events
    
    @property   
    def observables(self):
        raise NotImplementedError("observables property not implemented yet")
    
    @property
    def event_publisher(self) -> "EventPublisher":
        """
        event publishing PUB socket owning object, valid only after 
        ``run()`` is called, otherwise raises AttributeError.
        """
        return self._event_publisher 
                   
    @event_publisher.setter
    def event_publisher(self, value : "EventPublisher") -> None:
        from .thing import Thing

        if self._event_publisher is not None:
            raise AttributeError("Can set event publisher only once")
        if value is None:
            return 
        
        def recusively_set_event_publisher(obj : Thing, publisher : "EventPublisher") -> None:
            for name, evt in inspect._getmembers(obj, lambda o: isinstance(o, Event), getattr_without_descriptor_read):
                assert isinstance(evt, Event), "object is not an event"
                # above is type definition
                evt._publisher = publisher
            for name, subobj in inspect._getmembers(obj, lambda o: isinstance(o, Thing), getattr_without_descriptor_read):
                if name == '_owner':
                    continue 
                recusively_set_event_publisher(subobj, publisher)
            obj._event_publisher = publisher            

        recusively_set_event_publisher(self, value)


from ..protocols.zmq.brokers import EventPublisher

__all__ = [
    Event.__name__,
]