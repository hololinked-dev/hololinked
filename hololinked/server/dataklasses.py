"""
The following is a list of all dataclasses used to store information on the exposed 
resources on the network. These classese are generally not for consumption by the package-end-user. 
"""
import typing
import platform
import inspect
from enum import Enum
from dataclasses import dataclass, asdict, field, fields
from types import FunctionType, MethodType

from ..param.parameters import String, Boolean, Tuple, TupleSelector, ClassSelector, Parameter
from ..param.parameterized import ParameterizedMetaclass, ParameterizedFunction
from .constants import JSON, USE_OBJECT_NAME, UNSPECIFIED, HTTP_METHODS, REGEX, JSONSerializable, ResourceTypes, http_methods 
from .utils import get_signature, getattr_without_descriptor_read, pep8_to_URL_path
from .config import global_config
from .schema_validators import BaseSchemaValidator


class RemoteResourceInfoValidator:
    """
    A validator class for saving remote access related information on a resource. Currently callables (functions, 
    methods and those with__call__) and class/instance property store this information as their own attribute under 
    the variable ``_remote_info``. This is later split into information suitable for HTTP server, RPC client & ``EventLoop``. 
    
    Attributes
    ----------
    URL_path : str, default - extracted object name 
        the path in the URL under which the object is accesible.
        Must follow url-regex ('[\-a-zA-Z0-9@:%._\/\+~#=]{1,256}') requirement. 
        If not specified, the name of object will be used. Underscores will be converted to dashes 
        for PEP 8 names. 
    http_method : str, default POST
        HTTP request method under which the object is accessible. GET, POST, PUT, DELETE or PATCH are supported. 
    state : str, default None
        State machine state at which a callable will be executed or attribute/property can be 
        written. Does not apply to read-only attributes/properties. 
    obj_name : str, default - extracted object name
        the name of the object which will be supplied to the ``ObjectProxy`` class to populate
        its own namespace. For HTTP clients, HTTP method and URL path is important and for 
        object proxies clients, the obj_name is important. 
    iscoroutine : bool, default False 
        whether the callable should be awaited
    isaction : bool, default False 
        True for a method or function or callable
    isproperty : bool, default False
        True for a property
    """
    URL_path = String(default=USE_OBJECT_NAME,
                    doc="the path in the URL under which the object is accesible.") # type: str
    http_method = TupleSelector(default=HTTP_METHODS.POST, objects=http_methods, accept_list=True,
                    doc="HTTP request method under which the object is accessible. GET, POST, PUT, DELETE or PATCH are supported.") # typing.Tuple[str]
    state = Tuple(default=None, item_type=(Enum, str), allow_None=True, accept_list=True, accept_item=True,
                    doc="State machine state at which a callable will be executed or attribute/property can be written.") # type: typing.Union[Enum, str]
    obj = ClassSelector(default=None, allow_None=True, class_=(FunctionType, MethodType, classmethod, Parameter, ParameterizedMetaclass), # Property will need circular import so we stick to base class Parameter
                    doc="the unbound object like the unbound method")
    obj_name = String(default=USE_OBJECT_NAME, 
                    doc="the name of the object which will be supplied to the ``ObjectProxy`` class to populate its own namespace.") # type: str
    isaction = Boolean(default=False,
                    doc="True for a method or function or callable") # type: bool
    isproperty = Boolean(default=False,
                    doc="True for a property") # type: bool
    
    def __init__(self, **kwargs) -> None:
        """   
        No full-scale checks for unknown keyword arguments as the class 
        is used by the developer, so please try to be error-proof
        """
        if kwargs.get('URL_path', None) is not None:
            if not isinstance(kwargs['URL_path'], str): 
                raise TypeError(f"URL path must be a string. Given type {type(kwargs['URL_path'])}")
            if kwargs["URL_path"] != USE_OBJECT_NAME and not kwargs["URL_path"].startswith('/'):
                raise ValueError(f"URL path must start with '/'. Given value {kwargs['URL_path']}")
        for key, value in kwargs.items(): 
            setattr(self, key, value)
    
    def to_dataclass(self, obj : typing.Any = None, bound_obj : typing.Any = None) -> "RemoteResource":
        """
        For a plain, faster and uncomplicated access, a dataclass in created & used by the
        event loop. 
        
        Parameters
        ----------
        obj : Union[Property | Callable]  
            property or method/action

        bound_obj : owner instance
            ``Thing`` instance
       
        Returns
        -------
        RemoteResource
            dataclass equivalent of this object
        """
        return RemoteResource(
                    state=tuple(self.state) if self.state is not None else None, 
                    obj_name=self.obj_name, isaction=self.isaction, 
                    isproperty=self.isproperty, obj=obj, bound_obj=bound_obj, 
                ) 
        # http method is manually always stored as a tuple
    

class ActionInfoValidator(RemoteResourceInfoValidator):
    """
    request_as_argument : bool, default False
        if True, http/RPC request object will be passed as an argument to the callable. 
        The user is warned to not use this generally. 
    argument_schema: JSON, default None
        JSON schema validations for arguments of a callable. Assumption is therefore arguments will be JSON complaint. 
    return_value_schema: JSON, default None 
        schema for return value of a callable. Assumption is therefore return value will be JSON complaint.
    create_task: bool, default True
        default for async methods/actions 
    safe: bool, default True
        metadata information whether the action is safe to execute
    idempotent: bool, default False
        metadata information whether the action is idempotent
    synchronous: bool, default True
        metadata information whether the action is synchronous
    """
    request_as_argument = Boolean(default=False,
                    doc="if True, http/RPC request object will be passed as an argument to the callable.") # type: bool
    argument_schema = ClassSelector(default=None, allow_None=True, class_=dict, 
                    # due to schema validation, this has to be a dict, and not a special dict like TypedDict
                    doc="JSON schema validations for arguments of a callable")
    return_value_schema = ClassSelector(default=None, allow_None=True, class_=dict, 
                    # due to schema validation, this has to be a dict, and not a special dict like TypedDict
                    doc="schema for return value of a callable")
    create_task = Boolean(default=True, 
                        doc="should a coroutine be tasked or run in the same loop?") # type: bool
    iscoroutine = Boolean(default=False, # not sure if isFuture or isCoroutine is correct, something to fix later
                    doc="whether the callable should be awaited") # type: bool
    safe = Boolean(default=True,
                    doc="metadata information whether the action is safe to execute") # type: bool
    idempotent = Boolean(default=False,
                    doc="metadata information whether the action is idempotent") # type: bool
    synchronous = Boolean(default=True,
                    doc="metadata information whether the action is synchronous") # type: bool
    isparameterized = Boolean(default=False,
                    doc="True for a parameterized function") # type: bool


    def to_dataclass(self, obj : typing.Any = None, bound_obj : typing.Any = None) -> "RemoteResource":
        return ActionResource(
                    state=tuple(self.state) if self.state is not None else None, 
                    obj_name=self.obj_name, isaction=self.isaction, iscoroutine=self.iscoroutine,
                    isproperty=self.isproperty, obj=obj, bound_obj=bound_obj, 
                    schema_validator=(bound_obj.schema_validator)(self.argument_schema) if not global_config.validate_schema_on_client and self.argument_schema else None,
                    create_task=self.create_task, isparameterized=self.isparameterized
                ) 
    


class SerializableDataclass:
    """
    Presents uniform serialization for serializers using getstate and setstate and json 
    serialization.
    """
    def json(self):
        return asdict(self)

    def __getstate__(self):
        return self.json()
    
    def __setstate__(self, values : typing.Dict):
        for key, value in values.items():
            setattr(self, key, value)


__dataclass_kwargs = dict(frozen=True)
if float('.'.join(platform.python_version().split('.')[0:2])) >= 3.11:
    __dataclass_kwargs["slots"] = True

@dataclass(**__dataclass_kwargs)
class RemoteResource(SerializableDataclass):
    """
    This container class is used by the ``EventLoop`` methods (for example ``execute_once()``) to access resource 
    metadata instead of directly using ``RemoteResourceInfoValidator``. Instances of this dataclass is stored under 
    ``Thing.instance_resources`` dictionary for each property & method/action. Events use similar dataclass with 
    metadata but with much less information. 

    Attributes
    ----------
    state : str
        State machine state at which a callable will be executed or attribute/property can be 
        written. Does not apply to read-only attributes/properties. 
    obj_name : str, default - extracted object name
        the name of the object which will be supplied to the ``ObjectProxy`` class to populate
        its own namespace. For HTTP clients, HTTP method and URL path is important and for 
        object proxies clients, the obj_name is important. 
    isaction : bool
        True for a method or function or callable
    isproperty : bool
        True for a property
    obj : Union[Property | Callable]  
            property or method/action
    bound_obj : owner instance
        ``Thing`` instance
    """
    state : typing.Optional[typing.Union[typing.Tuple, str]] 
    obj_name : str 
    isaction : bool 
    isproperty : bool
    obj : typing.Any
    bound_obj : typing.Any
    
    def json(self):
        """
        return this object as a JSON serializable dictionary
        """
        # try:
        #     return self._json # accessing dynamic attr from frozen object
        # except AttributeError: # always causes attribute error when slots are True
        json_dict = {}
        for field in fields(self):
            if field.name != 'obj' and field.name != 'bound_obj':
                json_dict[field.name] = getattr(self, field.name)
        # object.__setattr__(self, '_json', json_dict) # because object is frozen - used to work, but not now 
        return json_dict     


@dataclass(**__dataclass_kwargs)
class ActionResource(RemoteResource):  
    """
    Attributes
    ----------
    iscoroutine : bool
        whether the callable should be awaited
    schema_validator : BaseSchemaValidator
        schema validator for the callable if to be validated server side
    """ 
    iscoroutine : bool
    schema_validator : typing.Optional[BaseSchemaValidator]
    create_task : bool 
    isparameterized : bool
    # no need safe, idempotent, synchronous


@dataclass
class HTTPMethodInstructions(SerializableDataclass):
    """
    contains a map of unique strings that identifies the resource operation for each HTTP method, thus acting as 
    instructions to be passed to the RPC server. The unique strings are generally made using the URL_path. 
    """
    GET :  typing.Optional[str] = field(default=None)
    POST :  typing.Optional[str] = field(default=None)
    PUT :  typing.Optional[str] = field(default=None)
    DELETE :  typing.Optional[str] = field(default=None)
    PATCH : typing.Optional[str] = field(default=None) 

    def __post_init__(self):
        self.supported_methods()

    def supported_methods(self): # can be a property
        try: 
            return self._supported_methods
        except: 
            self._supported_methods = []
            for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                if isinstance(self.__dict__[method], str):
                    self._supported_methods.append(method)
            return self._supported_methods
    
    def __contains__(self, value):
        return value in self._supported_methods


@dataclass
class HTTPResource(SerializableDataclass):
    """
    Representation of the resource used by HTTP server for routing and passing information to RPC server on
    "what to do with which resource belonging to which thing? - read, write, execute?". 
    
    Attributes
    ----------

    what : str
        is it a property, method/action or event?
    instance_name : str
        The ``instance_name`` of the thing which owns the resource. Used by HTTP server to inform 
        the message brokers to send the instruction to the correct recipient thing.
    fullpath : str
        URL full path used for routing
    instructions : HTTPMethodInstructions
        unique string that identifies the resource operation for each HTTP method, generally made using the URL_path 
        (qualified URL path {instance name}/{URL path}).  
    argument_schema : JSON
        argument schema of the method/action for validation before passing over the instruction to the RPC server. 
    request_as_argument: bool
        pass the request as a argument to the callable. For HTTP server ``tornado.web.HTTPServerRequest`` will be passed. 
    """
    what : str 
    class_name : str # just metadata
    instance_name : str 
    obj_name : str
    fullpath : str
    instructions : HTTPMethodInstructions
    argument_schema : typing.Optional[JSON]
    request_as_argument : bool = field(default=False)
    
                                  
    def __init__(self, *, what : str, class_name : str, instance_name : str, obj_name : str, fullpath : str, 
                request_as_argument : bool = False, argument_schema : typing.Optional[JSON] = None, 
                **instructions) -> None:
        self.what = what 
        self.class_name = class_name
        self.instance_name = instance_name
        self.obj_name = obj_name
        self.fullpath = fullpath
        self.request_as_argument = request_as_argument
        self.argument_schema = argument_schema
        if instructions.get('instructions', None):
            self.instructions = HTTPMethodInstructions(**instructions.get('instructions', None))
        else: 
            self.instructions = HTTPMethodInstructions(**instructions)
    

@dataclass
class ZMQResource(SerializableDataclass): 
    """
    Representation of resource used by RPC clients for mapping client method/action calls, property read/writes & events
    to a server resource. Used to dynamically populate the ``ObjectProxy``

    Attributes
    ----------

    what : str
        is it a property, method/action or event?
    instance_name : str
        The ``instance_name`` of the thing which owns the resource. Used by RPC client to inform 
        message brokers to send the message to the correct recipient.
    instruction : str
        unique string that identifies the resource, generally made using the URL_path. Although URL path is a HTTP
        concept, it is still used as a unique identifier. 
    name : str
        the name of the resource (__name__)
    qualname : str
        the qualified name of the resource (__qualname__) 
    doc : str
        the docstring of the resource
    argument_schema : JSON
        argument schema of the method/action for validation before passing over the instruction to the RPC server. 
    """
    what : str 
    class_name : str # just metadata
    instance_name : str 
    id : str # identification on the server
    obj_name : str # what looks on the client
    qualname : str # qualified name to use by the client 
    doc : typing.Optional[str] # 
    top_owner : bool # in case of object compisition
    argument_schema : typing.Optional[JSON]
    return_value_schema : typing.Optional[JSON]
    request_as_argument : bool = field(default=False)

    def __init__(self, *, what : str, class_name : str, instance_name : str, id : str, obj_name : str,
                qualname : str, doc : str, top_owner : bool, argument_schema : typing.Optional[JSON] = None,
                return_value_schema : typing.Optional[JSON] = None, request_as_argument : bool = False) -> None:
        self.what = what 
        self.class_name = class_name
        self.instance_name = instance_name
        self.id = id
        self.obj_name = obj_name 
        self.qualname = qualname
        self.doc = doc
        self.top_owner = top_owner
        self.argument_schema = argument_schema
        self.return_value_schema = return_value_schema
        self.request_as_argument = request_as_argument

    def get_dunder_attr(self, __dunder_name : str):
        name = __dunder_name.strip('_')
        name = 'obj_name' if name == 'name' else name
        return getattr(self, name)


@dataclass
class ServerSentEvent(SerializableDataclass):
    """
    event name and socket address of events to be consumed by clients. 
  
    Attributes
    ----------
    name : str
        name of the event, must be unique
    obj_name: str
        name of the event variable used to populate the RPC client
    socket_address : str
        address of the socket
    unique_identifier: str
        unique ZMQ identifier used in PUB-SUB model
    what: str, default EVENT
        is it a property, method/action or event?
    """
    name : str = field(default=UNSPECIFIED)
    class_name : str = field(default=UNSPECIFIED)
    obj_name : str = field(default=UNSPECIFIED)
    class_name : str = field(default=UNSPECIFIED) # just metadata  
    unique_identifier : str = field(default=UNSPECIFIED)
    serialization_specific : bool = field(default=False)
    socket_address : str = field(default=UNSPECIFIED)
    what : str = field(default=ResourceTypes.EVENT)


def build_our_temp_TD(instance, authority : typing.Optional[str] = None , 
                    ignore_errors : bool = False) -> typing.Dict[str, JSONSerializable]:
    """
    A temporary extension of TD used to build GUI of thing control panel.
    Will be later replaced by a more sophisticated TD builder which is compliant to the actual spec & its theory.
    """
    from .thing import Thing

    assert isinstance(instance, Thing), f"got invalid type {type(instance)}"
    
    our_TD = instance.get_thing_description(authority=authority, ignore_errors=ignore_errors)
    our_TD["inheritance"] = [class_.__name__ for class_ in instance.__class__.mro()]

    for instruction, remote_info in instance.instance_resources.items(): 
        if remote_info.isaction and remote_info.obj_name in our_TD["actions"]:
            if isinstance(remote_info.obj, classmethod):
                our_TD["actions"][remote_info.obj_name]["type"] = 'classmethod'
            our_TD["actions"][remote_info.obj_name]["signature"] = get_signature(remote_info.obj)[0]
        elif remote_info.isproperty and remote_info.obj_name in our_TD["properties"]:
            our_TD["properties"][remote_info.obj_name].update(instance.__class__.properties.webgui_info(remote_info.obj)[remote_info.obj_name])
    return our_TD



def get_organised_resources(instance):
    """
    organise the exposed attributes, actions and events into the dataclasses defined above
    so that the specific servers and event loop can use them. 
    """
    from .thing import Thing
    from .events import Event, EventDispatcher
    from .property import Property

    assert isinstance(instance, Thing), f"got invalid type {type(instance)}"

    httpserver_resources = dict() # type: typing.Dict[str, HTTPResource]
    # The following dict will be given to the object proxy client
    zmq_resources = dict() # type: typing.Dict[str, ZMQResource]
    # The following dict will be used by the event loop
    instance_resources = dict() # type: typing.Dict[str, typing.Union[RemoteResource, ActionResource]] 
    # create URL prefix
    if instance._owner is not None: 
        instance._full_URL_path_prefix = f'{instance._owner._full_URL_path_prefix}/{instance.instance_name}' 
    else:
        instance._full_URL_path_prefix = f'/{instance.instance_name}' # leading '/' was stripped at init
    
    # First add methods and callables
    # properties
    for prop in instance.parameters.descriptors.values():
        if isinstance(prop, Property) and hasattr(prop, '_remote_info') and prop._remote_info is not None: 
            if not isinstance(prop._remote_info, RemoteResourceInfoValidator): 
                raise TypeError("instance member {} has unknown sub-member '_remote_info' of type {}.".format(
                            prop, type(prop._remote_info))) 
                # above condition is just a gaurd in case somebody does some unpredictable patching activities
            remote_info = prop._remote_info
            fullpath = f"{instance._full_URL_path_prefix}{remote_info.URL_path}"
            read_http_method = write_http_method = delete_http_method = None
            if len(remote_info.http_method) == 1:
                read_http_method = remote_info.http_method[0]
                instructions = { read_http_method : f"{fullpath}/read" }
            elif len(remote_info.http_method) == 2:
                read_http_method, write_http_method = remote_info.http_method
                instructions = { 
                    read_http_method : f"{fullpath}/read", 
                    write_http_method : f"{fullpath}/write"
                }
            else:
                read_http_method, write_http_method, delete_http_method = remote_info.http_method
                instructions = {
                    read_http_method : f"{fullpath}/read", 
                    write_http_method : f"{fullpath}/write", 
                    delete_http_method : f"{fullpath}/delete"
                }
                
            httpserver_resources[fullpath] = HTTPResource(
                                                what=ResourceTypes.PROPERTY, 
                                                class_name=instance.__class__.__name__,
                                                instance_name=instance._owner.instance_name if instance._owner is not None else instance.instance_name,
                                                obj_name=remote_info.obj_name,
                                                fullpath=fullpath,
                                                **instructions
                                            )
            zmq_resources[fullpath] = ZMQResource(
                            what=ResourceTypes.PROPERTY, 
                            class_name=instance.__class__.__name__,
                            instance_name=instance._owner.instance_name if instance._owner is not None else instance.instance_name, 
                            instruction=fullpath, 
                            doc=prop.__doc__, 
                            obj_name=remote_info.obj_name,
                            qualname=instance.__class__.__name__ + '.' + remote_info.obj_name,
                            # qualname is not correct probably, does not respect inheritance
                            top_owner=instance._owner is None,
                        ) 
            data_cls = remote_info.to_dataclass(obj=prop, bound_obj=instance) 
            instance_resources[f"{fullpath}/read"] = data_cls
            instance_resources[f"{fullpath}/write"] = data_cls  
            instance_resources[f"{fullpath}/delete"] = data_cls  
            if prop._observable:
                # There is no real philosophy behind this logic flow, we just set the missing information.
                assert isinstance(prop._observable_event_descriptor, Event), f"observable event not yet set for {prop.name}. logic error."
                evt_fullpath = f"{instance._full_URL_path_prefix}{prop._observable_event_descriptor.URL_path}"
                dispatcher = EventDispatcher(evt_fullpath)
                dispatcher._remote_info.class_name = instance.__class__.__name__
                dispatcher._remote_info.serialization_specific = instance.zmq_serializer != instance.http_serializer
                setattr(instance, prop._observable_event_descriptor._obj_name, dispatcher)
                # prop._observable_event_descriptor._remote_info.unique_identifier = evt_fullpath
                httpserver_resources[evt_fullpath] = dispatcher._remote_info
                zmq_resources[evt_fullpath] = dispatcher._remote_info
    # Methods
    for name, resource in inspect._getmembers(instance, lambda f : inspect.ismethod(f) or (
                                hasattr(f, '_remote_info') and isinstance(f._remote_info, ActionInfoValidator)),
                                                 getattr_without_descriptor_read): 
        if hasattr(resource, '_remote_info'):
            if not isinstance(resource._remote_info, ActionInfoValidator):
                raise TypeError("instance member {} has unknown sub-member '_remote_info' of type {}.".format(
                            resource, type(resource._remote_info))) 
            remote_info = resource._remote_info
            # methods are already bound
            assert remote_info.isaction, ("remote info from inspect.ismethod is not a callable",
                                "logic error - visit https://github.com/VigneshVSV/hololinked/issues to report")
            fullpath = f"{instance._full_URL_path_prefix}{remote_info.URL_path}" 
            instruction = f"{fullpath}/invoke-on-{remote_info.http_method[0]}" 
            # needs to be cleaned up for multiple HTTP methods
            httpserver_resources[instruction] = HTTPResource(
                                        what=ResourceTypes.ACTION,
                                        class_name=instance.__class__.__name__,
                                        instance_name=instance._owner.instance_name if instance._owner is not None else instance.instance_name,
                                        obj_name=remote_info.obj_name,
                                        fullpath=fullpath,
                                        argument_schema=remote_info.argument_schema,
                                        request_as_argument=remote_info.request_as_argument,
                                        **{ http_method : instruction for http_method in remote_info.http_method },
                                    )
            zmq_resources[instruction] = ZMQResource(
                                            what=ResourceTypes.ACTION,
                                            class_name=instance.__class__.__name__,
                                            instance_name=instance._owner.instance_name if instance._owner is not None else instance.instance_name,
                                            instruction=instruction,                                                                                                                                                                                        
                                            obj_name=getattr(resource, '__name__'),
                                            qualname=getattr(resource, '__qualname__'), 
                                            doc=getattr(resource, '__doc__'),
                                            top_owner=instance._owner is None,
                                            argument_schema=remote_info.argument_schema,
                                            return_value_schema=remote_info.return_value_schema,
                                            request_as_argument=remote_info.request_as_argument
                                        )
            instance_resources[instruction] = remote_info.to_dataclass(obj=resource, bound_obj=instance)   
    # Events
    for name, resource in inspect._getmembers(instance, lambda o : isinstance(o, Event), getattr_without_descriptor_read):
        assert isinstance(resource, Event), ("thing event query from inspect.ismethod is not an Event",
                                    "logic error - visit https://github.com/VigneshVSV/hololinked/issues to report")    
        # above assertion is only a typing convenience
        fullpath = f"{instance._full_URL_path_prefix}{resource.URL_path}"
        # resource._remote_info.unique_identifier = fullpath
        dispatcher = EventDispatcher(fullpath)
        dispatcher._remote_info.class_name = instance.__class__.__name__
        dispatcher._remote_info.serialization_specific = instance.zmq_serializer != instance.http_serializer
        setattr(instance, name, dispatcher) # resource._remote_info.unique_identifier))
        httpserver_resources[fullpath] = dispatcher._remote_info
        zmq_resources[fullpath] = dispatcher._remote_info
    # Other objects
    for name, resource in inspect._getmembers(instance, lambda o : isinstance(o, Thing), getattr_without_descriptor_read):
        assert isinstance(resource, Thing), ("thing children query from inspect.ismethod is not a Thing",
                                    "logic error - visit https://github.com/VigneshVSV/hololinked/issues to report")
        # above assertion is only a typing convenience
        if name == '_owner': 
            # second condition allows sharing of Things without adding once again to the list of exposed resources
            # for example, a shared logger 
            continue
        if resource._owner is None:
            resource._owner = instance
            resource._prepare_resources()
        httpserver_resources.update(resource.httpserver_resources)
        # zmq_resources.update(resource.zmq_resources)
        instance_resources.update(resource.instance_resources)
   
    # The above for-loops can be used only once, the division is only for readability
    # following are in _internal_fixed_attributes - allowed to set only once
    return zmq_resources, httpserver_resources, instance_resources    