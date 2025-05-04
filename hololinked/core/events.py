import typing 
import jsonschema

from ..param.parameterized import Parameterized, ParameterizedMetaclass
from ..constants import JSON 
from ..utils import pep8_to_dashed_name
from ..config import global_config




class Event:
    """
    Asynchronously push arbitrary messages to clients. Apart from default events created by the package (like state
    change event, observable properties etc.), events are supposed to be created at class level or at `__init__` 
    as a instance attribute, otherwise their publishing socket is unbound and will lead to `AttributeError`.  

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

    __slots__ = ['name', '_internal_name', '_publisher', '_observable',
                'doc', 'schema', 'security', 'label', 'owner']


    def __init__(self, doc : typing.Optional[str] = None, 
                schema : typing.Optional[JSON] = None, # security : typing.Optional[BaseSecurityDefinition] = None,
                label : typing.Optional[str] = None) -> None:
        self.doc = doc 
        if global_config.validate_schemas and schema:
            jsonschema.Draft7Validator.check_schema(schema)
        self.schema = schema
        # self.security = security
        self.label = label
        self._observable = False
       
    def __set_name__(self, owner: ParameterizedMetaclass, name: str) -> None:
        self._internal_name = pep8_to_dashed_name(name)
        self.name = name
        self.owner = owner

    @typing.overload
    def __get__(self, obj, objtype) -> "EventDispatcher":
        ...

    def __get__(self, obj: Parameterized, objtype: ParameterizedMetaclass = None):
        try:
            if not obj:
                return self
            # uncomment for type hinting
            # from .thing import Thing
            # assert isinstance(obj, Thing)
            return EventDispatcher(
                unique_identifier=f'{obj._qualified_id}/{self._internal_name}',
                publisher=obj.rpc_server.event_publisher if obj.rpc_server else None,
                owner_inst=obj
            )
        except KeyError:
            raise AttributeError("Event object not yet initialized, please dont access now." +
                                " Access after Thing is running.")
        
    def to_affordance(self, owner_inst):
        from ..td import EventAffordance
        return EventAffordance.generate(self, owner_inst)
        
    
class EventDispatcher:
    """
    The actual worker which pushes the event. The separation is necessary between `Event` and 
    `EventDispatcher` to allow class level definitions of the `Event` 
    """

    __slots__ = ['_unique_identifier', '_unique_zmq_identifier', '_unique_http_identifier',
                '_publisher', '_owner_inst']

    def __init__(self, unique_identifier: str, publisher: "EventPublisher", owner_inst: ParameterizedMetaclass) -> None:
        self._unique_identifier = bytes(unique_identifier, encoding='utf-8')   
        self.publisher = publisher
        self._owner_inst = owner_inst

    @property
    def publisher(self) -> "EventPublisher": 
        """
        Event publishing PUB socket owning object.
        """
        return self._publisher
    
    @publisher.setter
    def publisher(self, value: "EventPublisher") -> None:
        if not hasattr(self, '_publisher'):
            self._publisher = value
        elif not isinstance(value, EventPublisher):
            raise AttributeError("Publisher must be of type EventPublisher. Given type: " + str(type(value)))

    def push(self, data: typing.Any = None, *, serialize: bool = True, **kwargs) -> None:
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
                pushes event to RPC clients, irrelevant if `Thing` uses only one type of serializer (refer to 
                difference between zmq_serializer and http_serializer).
            http_clients: bool, default True
                pushed event to HTTP clients, irrelevant if `Thing` uses only one type of serializer (refer to 
                difference between zmq_serializer and http_serializer).
        """
        self.publisher.publish(self, data, zmq_clients=kwargs.get('zmq_clients', True), 
                                http_clients=kwargs.get('http_clients', True), serialize=serialize)


    def receive_acknowledgement(self, timeout : typing.Union[float, int, None]) -> bool:
        """
        Receive acknowlegement for event receive. When the timeout argument is present and not None, 
        it should be a floating point number specifying a timeout for the operation in seconds (or fractions thereof).
        """
        raise NotImplementedError("Event acknowledgement is not implemented yet.")
        return self._synchronize_event.wait(timeout=timeout)

    def _set_acknowledgement(self, *args, **kwargs) -> None:
        """
        Method to be called by RPC server when an acknowledgement is received. Not for user to be set.
        """
        raise NotImplementedError("Event acknowledgement is not implemented yet.")
        self._synchronize_event.set()
        


from .zmq.brokers import EventPublisher

__all__ = [
    Event.__name__,
]