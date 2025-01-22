"""
The following is a list of all dataclasses used to store information on the exposed 
resources on the network. These classese are generally not for consumption by the package-end-user. 
"""
import typing
import platform
import warnings
import inspect
from enum import Enum
from dataclasses import dataclass, fields
from types import FunctionType, MethodType

from ..param.parameters import String, Boolean, Tuple, ClassSelector, Parameter
from ..param.parameterized import ParameterizedMetaclass
from ..constants import JSON, USE_OBJECT_NAME, UNSPECIFIED, REGEX, JSONSerializable, ResourceTypes
from ..utils import SerializableDataclass, get_signature, pep8_to_dashed_name
from ..config import global_config
from ..schema_validators import BaseSchemaValidator


class RemoteResourceInfoValidator:
    """
    A validator class for saving remote access related information on a resource. Currently callables (functions, 
    methods and those with__call__) and class/instance property store this information as their own attribute under 
    the variable ``_execution_info_validator``. This is later split into information suitable for HTTP server, ZMQ client & ``EventLoop``. 
    
    Attributes
    ----------
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
        for key, value in kwargs.items(): 
            setattr(self, key, value)
    
    

class ActionInfoValidator(RemoteResourceInfoValidator):
    """
    request_as_argument : bool, default False
        if True, http/ZMQ request object will be passed as an argument to the callable. 
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
    isclassmethod = Boolean(default=False,
                    doc="True for a classmethod") # type: bool
    schema_validator = ClassSelector(default=None, allow_None=True, class_=BaseSchemaValidator,
                    doc="schema validator for the callable if to be validated server side") # type: BaseSchemaValidator

    

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

    for instruction, remote_info in instance.zmq_resources.items(): 
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
    from .property import Property 
    from .events import Event, EventDispatcher

    assert isinstance(instance, Thing), f"got invalid type {type(instance)}"

    zmq_resources = dict() # type: typing.Dict[str, ZMQResource]
    # The following dict will be used by the event loop
    # create unique identifier for the instance
    if instance._owner is not None: 
        instance._qualified_id = f'{instance._owner._qualified_id}.{instance.id}' 
    else:
        instance._qualified_id = instance.id

    # First add methods and callables
    # properties
    for prop in instance.properties.descriptors.values():
        if not isinstance(prop, Property) or prop._execution_info_validator is None:
            continue 
        if not isinstance(prop._execution_info_validator, RemoteResourceInfoValidator): 
            raise TypeError("instance member {} has unknown sub-member '_execution_info_validator' of type {}.".format(
                        prop, type(prop._execution_info_validator))) 
            # above condition is just a gaurd in case somebody does some unpredictable patching activities
        execution_info = prop._execution_info_validator     
        if execution_info.obj_name in zmq_resources:
            raise ValueError(f"Duplicate resource name {execution_info.obj_name} found in {instance.__class__.__name__}")
        zmq_resources[execution_info.obj_name] = ZMQResource(
                                    what=ResourceTypes.PROPERTY, 
                                    class_name=instance.__class__.__name__,
                                    id=instance.id, 
                                    obj_name=execution_info.obj_name,
                                    qualname=instance.__class__.__name__ + '.' + execution_info.obj_name,
                                    doc=prop.__doc__
                                ) 
        prop.execution_info = execution_info.to_dataclass(obj=prop, bound_obj=instance) 
        del prop._execution_info_validator
        if not prop._observable:
            continue
        # observable properties
        assert isinstance(prop._observable_event_descriptor, Event), f"observable event not yet set for {prop.name}. logic error."
        unique_identifier = f"{instance._qualified_id}/{pep8_to_dashed_name(prop._observable_event_descriptor.friendly_name)}"
        dispatcher = EventDispatcher(unique_identifier=unique_identifier, publisher=prop._observable_event_descriptor._publisher)
        prop._observable_event_descriptor.__set__(instance, dispatcher)
        prop._observable_event_descriptor.publisher.register(dispatcher)     
        remote_info = ZMQEvent(
                                what=ResourceTypes.EVENT,
                                class_name=instance.__class__.__name__,
                                id=instance.id,
                                obj_name=prop._observable_event_descriptor.name,
                                friendly_name=prop._observable_event_descriptor.friendly_name,
                                qualname=f'{instance.__class__.__name__}.{prop._observable_event_descriptor.name}',
                                unique_identifier=unique_identifier,
                                socket_address=dispatcher.publisher.socket_address,
                                serialization_specific=dispatcher._unique_zmq_identifier != dispatcher._unique_zmq_identifier,
                                doc=prop._observable_event_descriptor.doc
                            )         
        if unique_identifier in zmq_resources:
            raise ValueError(f"Duplicate resource name {unique_identifier} found in {instance.__class__.__name__}")                 
        zmq_resources[unique_identifier] = remote_info
    # methods
    for name, action in instance.actions.items():
        if not isinstance(action._execution_info_validator, ActionInfoValidator):
            raise TypeError("instance member {} has unknown sub-member '_execution_info_validator' of type {}.".format(
                        action, type(action._execution_info_validator)) + 
                        " This is a reserved variable, please dont modify it.") 
        execution_info = action._execution_info_validator
        if execution_info.obj_name in zmq_resources:
            warnings.warn(f"Duplicate resource name {execution_info.obj_name} found in {instance.__class__.__name__}", 
                        UserWarning)
        # methods are already bound
        assert execution_info.isaction, ("remote info from inspect.ismethod is not a callable",
                            "logic error - visit https://github.com/VigneshVSV/hololinked/issues to report")
        # needs to be cleaned up for multiple HTTP methods
        zmq_resources[execution_info.obj_name] = ZMQAction(
                                        what=ResourceTypes.ACTION,
                                        class_name=instance.__class__.__name__,
                                        id=instance.id,
                                        obj_name=getattr(action, '__name__'),
                                        qualname=getattr(action, '__qualname__'), 
                                        doc=getattr(action, '__doc__'),
                                        argument_schema=execution_info.argument_schema,
                                        return_value_schema=execution_info.return_value_schema,
                                        request_as_argument=execution_info.request_as_argument
                                    )
        action.execution_info = execution_info.to_dataclass(obj=action, bound_obj=instance)  
    # Events
    for name, evt in instance.events.items():
        assert isinstance(evt, Event), ("thing event query from inspect.ismethod is not an Event",
                                    "logic error - visit https://github.com/VigneshVSV/hololinked/issues to report")
        if getattr(instance, name, None):
            continue
        # above assertion is only a typing convenience
        unique_identifier = f"{instance._qualified_id}{pep8_to_dashed_name(evt.friendly_name)}"
        if unique_identifier in zmq_resources:
            raise ValueError(f"Duplicate resource name {unique_identifier} found in {instance.__class__.__name__}")
        dispatcher = EventDispatcher(unique_identifier=unique_identifier, publisher=evt._publisher)
        evt.__set__(instance, dispatcher)
        evt._publisher.register(dispatcher)
        remote_info = ZMQEvent(
                            what=ResourceTypes.EVENT,
                            class_name=instance.__class__.__name__,
                            id=instance.id,
                            obj_name=name,
                            friendly_name=evt.friendly_name,
                            qualname=f'{instance.__class__.__name__}.{name}',
                            unique_identifier=unique_identifier,
                            serialization_specific=dispatcher._unique_zmq_identifier != dispatcher._unique_zmq_identifier,
                            socket_address=dispatcher.publisher.socket_address,
                            doc=evt.doc,             
                        )       
        zmq_resources[unique_identifier] = remote_info
    # Other objects
    for name, resource in instance.sub_things.items():
        assert isinstance(resource, Thing), ("thing children query from inspect.ismethod is not a Thing",
                                    "logic error - visit https://github.com/VigneshVSV/hololinked/issues to report")
        # above assertion is only a typing convenience
        if name == '_owner': 
            # second condition allows sharing of Things without adding once again to the list of exposed resources
            # for example, a shared logger 
            continue
        resource._owner = instance      
        resource._prepare_resources() # trigger again after the owner has been set to make it work correctly
        if resource._qualified_id in zmq_resources:
            raise ValueError(f"Duplicate resource name {resource.id} found in {instance.__class__.__name__}")
        zmq_resources[resource._qualified_id] = ZMQResource(
                                                            what=ResourceTypes.THING,
                                                            class_name=resource.__class__.__name__,
                                                            id=resource.id,
                                                            obj_name=name,
                                                            qualname=f'{instance.__class__.__name__}.{resource.__class__.__name__}',
                                                            doc=resource.__doc__,
                                                            request_as_argument=False
                                                        )
    
   
    # The above for-loops can be used only once, the division is only for readability
    # following are in _internal_fixed_attributes - allowed to set only once
    return zmq_resources