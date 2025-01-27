
import copy
import inspect
from types import FunctionType
import typing

from ..param.parameterized import (EventResolver, EventDispatcher, Parameter, Parameterized, 
                            ParameterizedMetaclass, ClassParameters,
                            edit_constant as edit_constant_parameters)
from ..utils import getattr_without_descriptor_read
from ..constants import JSON, JSONSerializable
from ..serializers import Serializers
from .actions import Action, BoundAction
from .property import Property
from .events import Event, EventPublisher



class ThingMeta(ParameterizedMetaclass):
    """
    Metaclass for `Thing`, implements a `__post_init__()` call and instantiation of a registry for properties', actions'
    and events' descriptor objects. `__post_init__()` is run after the user's `__init__()` method and properties that can be 
    loaded from a database are written at this time. 	
    Accessing properties, actions and events at the class level returns the descriptor object through the `DescriptorRegistry`
    implementation. Accessing properties, actions and events at instance level can return their values and the descriptors 
    can be accessed through the `descriptors` property.
    """
    def __init__(mcs, name, bases, dict_):
        super().__init__(name, bases, dict_)
        mcs._create_actions_registry()
        mcs._create_events_registry()

    def __call__(mcls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        instance.__post_init__()
        return instance
    
    def _create_param_container(cls, cls_members: dict) -> None:
        """
        creates `PropertyRegistry` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All properties have definitions 
        copied from `param`.
        """
        cls._param_container = PropertyRegistry(cls, cls_members)

    def _create_actions_registry(cls) -> None:
        """
        creates `Actions` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All actions have definitions 
        copied from `param`.
        """
        cls._actions_registry = ActionsRegistry(cls)

    def _create_events_registry(cls) -> None:
        """
        creates `Events` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All events have definitions 
        copied from `param`.
        """
        cls._events_registry = EventsRegistry(cls)

    @property
    def properties(cls) -> "PropertyRegistry":
        """
        Container object for Property descriptors. Returns `PropertyRegistry` instance instead of `param`'s own 
        `Parameters` instance. 
        """
        return cls._param_container
    
    @property
    def actions(cls) -> "ActionsRegistry":
        """Container object for Action descriptors"""
        return cls._actions_registry
    
    @property
    def events(cls) -> "EventsRegistry":
        """Container object for Event descriptors"""
        return cls._events_registry
       


class DescriptorRegistry:
    """
    A registry for the descriptors of a `Thing` class or `Thing` instance. 
    Provides a dictionary interface to access the descriptors under the `descriptors` attribute. 
    Each of properties, actions and events subclasss from here to implement a registry of their available objects. 
    """

    def __init__(self, owner_cls: ThingMeta, owner_inst = None) -> None:
        """
        Parameters
        ----------
        owner_cls: ThingMeta
            The class/subclass of the `Thing` that owns the registry.
        owner_inst: Thing
            The instance of the `Thing` that owns the registry, optional
        """
        super().__init__()
        self.owner_cls = owner_cls
        self.owner_inst = owner_inst
        self.clear() 
    

    @property
    def owner(self):
        """
        The owner of the registry - the instance of a `Thing` if a `Thing` has been instantiated 
        or the class/subclass of `Thing` when accessed as a class attribute.
        """
        return self.owner_inst if self.owner_inst is not None else self.owner_cls
    
    @property   
    def _qualified_prefix(self) -> str:
        """
        A unique prefix for `descriptors` attribute according to the `Thing`'s subclass and instance id. 
        For internal use. 
        """
        try: 
            return self._qualified__prefix
        except AttributeError:
            prefix = inspect.getfile(self.__class__) + self.__class__.__name__.lower()
            if self.owner_inst is not None:
                prefix += f'_{self.owner_inst.id}'
            self._qualified__prefix = prefix
            return prefix
        
    @property
    def descriptor_object(self) -> type[Property | Action | Event]:
        """The type of descriptor object that this registry holds, i.e. `Property`, `Action` or `Event`"""
        raise NotImplementedError("Implement descriptor_object in subclass")
    
    @property
    def descriptors(self) -> typing.Dict[str, type[Property | Action | Event]]:
        """A dictionary with all the descriptors as values and their names as keys."""
        raise NotImplementedError("Implement descriptors in subclass")

    @property
    def names(self) -> typing.KeysView[str]:
        """The names of the descriptors objects as a dictionary key view"""
        return self.descriptors.keys()
    
    @property
    def values(self) -> typing.Dict[str, typing.Any]: 
        raise NotImplementedError("Implement values in subclass")
        
    def clear(self) -> None:
        """
        Deletes the descriptors dictionary (value of the `descriptors` proeprty) so that it can be recreated. 
        Does not delete the descriptors themselves. Call this method once if new descriptors are added to the 
        class/instance dynamically in runtime.
        """
        try:
            delattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}')
        except AttributeError:
            pass

    def __getitem__(self, key: str) -> Property | Action | Event:
        """Returns the descriptor object for the given key."""
        raise NotImplementedError("Implement __getitem__ in subclass")
    
    def __contains__(self, obj: Property | Action | Event) -> bool:
        """Returns True if the descriptor object is in the descriptors dictionary."""
        raise NotImplementedError("contains not implemented yet")
    
    def __dir__(self) -> typing.List[str]:
        """Adds descriptor object to the dir"""
        return super().__dir__() + self.descriptors().keys() # type: ignore
    
    def __iter__(self):
        """Iterates over the descriptors of this object."""
        yield from self.descriptors

    def __len__(self) -> int:
        """The number of descriptors in this object."""
        return len(self.descriptors)
    
    def __hash__(self) -> int:
        return hash(self._qualified__prefix)
    
    def __str__(self) -> int:
        if self.owner_inst:
            return f"<DescriptorRegistry({self.owner_cls.__name__}({self.owner_inst.id}))>"
        return f"<DescriptorRegistry({self.owner_cls.__name__})>"
    
    def get_descriptors(self, recreate: bool = False) -> typing.Dict[str, Property | Action | Event]:
        """
        a dictionary with all the properties of the object as values (methods that are decorated with `property`) and 
        their names as keys.
        """
        if recreate:
            self.clear()
        try:
            return getattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}')
        except AttributeError:
            descriptors = dict()
            for name, objekt in inspect._getmembers(
                        self.owner_cls, 
                        lambda f: isinstance(f, self.descriptor_object),
                        getattr_without_descriptor_read
                    ): 
                descriptors[name] = objekt
            setattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}', descriptors)
            # We cache the parameters because this method is called often,
            # and parameters are rarely added (and cannot be deleted)      
            return descriptors
    
    def _get_values(self) -> typing.Dict[str, typing.Any]:
        """
        the values contained within the descriptors after reading when accessed at instance level, otherwise, 
        the descriptor objects as dictionary when accessed at class level.
        For example, if a `Thing` instance's property contains a value of 5, this method will return 
        { <property name> : 5 } when accessed at instance level, and { <property name> : <property object> } when accessed 
        at class level.   
        """
        if self.owner_inst is None: 
            return self.descriptors
        values = dict()
        for name, value in self.descriptors.items():
            values[name] = value.__get__(self.owner_inst, self.owner_cls)
        return values

    
def supports_only_instance_access(
        error_msg: str = "This method is only supported at instance level"
    ) -> FunctionType:
    """
    decorator to raise an error if a method is called at class level instead of instance level
    within the registry functionality. 
    """
    def inner(func: FunctionType) -> FunctionType:
        def wrapper(self: DescriptorRegistry, *args, **kwargs):
            if self.owner_inst is None:
                error_msg = inner._error_msg
                raise AttributeError(error_msg)
            return func(self, *args, **kwargs)
        return wrapper
    inner._error_msg = error_msg
    return inner 


class PropertyRegistry(DescriptorRegistry):
    """
    A `DescriptorRegistry` for properties of a `Thing` class or `Thing` instance.
    """

    def __init__(self, owner_cls, owner_class_members: dict, owner_inst=None):
        super().__init__(owner_cls, owner_inst)
        """
        cls is the Parameterized class which is always set.
        self is the instance if set.
        """
        if self.owner_inst is None and owner_class_members is not None:
            # instantiated by class 
            self.event_resolver = EventResolver(owner_cls=owner_cls)
            self.event_dispatcher = EventDispatcher(owner_cls, self.event_resolver)
            self.event_resolver.create_unresolved_watcher_info(owner_class_members)
        else:
            # instantiated by instance
            self._instance_params = {}
            self.event_resolver = self.owner_cls.properties.event_resolver
            self.event_dispatcher = EventDispatcher(owner_inst, self.event_resolver)
            self.event_dispatcher.prepare_instance_dependencies()    
        
        
    @property
    def descriptor_object(self) -> type[Parameter]:
        return Parameter
    
    @property
    def descriptors(self) -> typing.Dict[str, Parameter]:
        if self.owner_inst is None:
            return super().get_descriptors()
        return dict(super().get_descriptors(), **self._instance_params)
    
    values = property(DescriptorRegistry._get_values,
                doc=DescriptorRegistry._get_values.__doc__) # type: typing.Dict[str, Parameter | Property | typing.Any]

    @typing.overload
    def __getitem__(self, key: str) -> Parameter:
        ... 

    def __getitem__(self, key: str) -> typing.Any:
        return self.descriptors[key]
    
    def __contains__(self, action: Parameter) -> bool:
        return action in self.values.values()
    
    @property
    def defaults(self) -> typing.Dict[str, typing.Any]:
        """default values of all properties as a dictionary with property names as keys"""
        defaults = {}
        for key, val in self.descriptors.items():
            defaults[key] = val.default
        return defaults
    
    @property
    def remote_objects(self) -> typing.Dict[str, Property]:
        """
        dictionary of properties that are remotely accessible (`remote=True`), 
        which is also a default setting for all properties
        """
        try:
            return getattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_remote')
        except AttributeError: 
            props = self.descriptors
            remote_props = {}
            for name, desc in props.items():
                if not isinstance(desc, Property):
                    continue
                if desc.is_remote: 
                    remote_props[name] = desc
            setattr(
                self, 
                f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_remote', 
                remote_props
            )
            return remote_props
        
    @property
    def db_objects(self) -> typing.Dict[str, Property]:
        """dictionary of properties that are stored or loaded from the database"""
        try:
            return getattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db')
        except AttributeError:
            propdict = self.descriptors
            db_props = {}
            for name, desc in propdict.items():
                if not isinstance(desc, Property):
                    continue
                if desc.db_init or desc.db_persist or desc.db_commit:
                    db_props[name] = desc
            setattr(
                self, 
                f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db', 
                db_props
            )
            return db_props
    
    @property
    def db_init_objects(self) -> typing.Dict[str, Property]:
        """dictionary of properties that are initialized from the database"""
        try:
            return getattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_init')
        except AttributeError:
            propdict = self.db_objects
            db_init_props = {}
            for name, desc in propdict.items():
                if desc.db_init or desc.db_persist:
                    db_init_props[name] = desc
            setattr(
                self,
                f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_init', 
                db_init_props
            )
            return db_init_props
        
    @property
    def db_commit_objects(self) -> typing.Dict[str, Property]:
        """dictionary of properties that are committed to the database"""
        try:
            return getattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_commit')
        except AttributeError:
            propdict = self.db_objects
            db_commit_props = {}
            for name, desc in propdict.items():
                if desc.db_commit or desc.db_persist:
                    db_commit_props[name] = desc
            setattr(
                self,
                f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_commit', 
                db_commit_props
            )
            return db_commit_props
    
    @property
    def db_persisting_objects(self) -> typing.Dict[str, Property]:
        """dictionary of properties that are persisted through the database"""
        try:
            return getattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_persisting')
        except AttributeError:
            propdict = self.db_objects
            db_persisting_props = {}
            for name, desc in propdict.items():
                if desc.db_persist:
                    db_persisting_props[name] = desc
            setattr(
                self,
                f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_persisting', 
                db_persisting_props
            )
            return db_persisting_props

    def get(self, **kwargs: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """
        read properties from the object, implements WoT operation `readAllProperties` and `readMultipleProperties`
        
        Parameters
        ----------
        **kwargs: typing.Dict[str, typing.Any]
            - `names`: List[str]
                list of property names to be fetched
            - name: str
                name of the property to be fetched, along with a 'rename' for the property in the response.
                For example { 'foo_prop' : 'fooProp' } will return the property 'foo_prop' as 'fooProp' in the response.
        """
        data = {}
        if len(kwargs) == 0:
            # read all properties
            for name, prop in self.remote_objects.items():
                if self.owner_inst is None and not prop.class_member:
                    continue
                data[name] = prop.__get__(self.owner_inst, self.owner_cls)
            return data
        elif 'names' in kwargs:
            names = kwargs.get('names')
            if not isinstance(names, (list, tuple, str)):
                raise TypeError("Specify properties to be fetched as a list, tuple or comma separated names. " + 
                                f"Given type {type(names)}")
            if isinstance(names, str):
                names = names.split(',')
            kwargs = {name: name for name in names}
        for requested_prop, rename in kwargs.items():
            if not isinstance(requested_prop, str):
                raise TypeError(f"property name must be a string. Given type {type(requested_prop)}")
            if not isinstance(rename, str):
                raise TypeError(f"requested new name must be a string. Given type {type(rename)}")
            if requested_prop not in self.descriptors:
                raise AttributeError(f"property {requested_prop} does not exist")
            if requested_prop not in self.remote_objects:
                raise AttributeError(f"property {requested_prop} is not remote accessible")
            prop = self.descriptors[requested_prop]
            if self.owner_inst is None and not prop.class_member:
                continue
            data[rename] = prop.__get__(self.owner_inst, self.owner_cls)                   
        return data 
       
    def set(self, **values : typing.Dict[str, typing.Any]) -> None:
        """ 
        set properties whose name is specified by keys of a dictionary; implements WoT operation `writeMultipleProperties`
        or `writeAllProperties`. 
        
        Parameters
        ----------
        values: typing.Dict[str, typing.Any]
            dictionary of property names and its values
        """
        errors = ''
        for name, value in values.items():
            try:
                if name not in self.descriptors:
                    raise AttributeError(f"property {name} does not exist")
                if name not in self.remote_objects:
                    raise AttributeError(f"property {name} is not remote accessible")
                prop = self.descriptors[name]
                if self.owner_inst is None and not prop.class_member:
                    raise AttributeError(f"property {name} is not a class member and cannot be set at class level")
                setattr(self.owner, name, value)
            except Exception as ex:
                errors += f'{name}: {str(ex)}\n'
        if errors:
            ex = RuntimeError("Some properties could not be set due to errors. " + 
                            "Check exception notes or server logs for more information.")
            ex.__notes__ = errors
            raise ex from None
        
    def add(self, name: str, config: JSON) -> None:
        """
        add a property to the object
        
        Parameters
        ----------
        name: str
            name of the property
        config: JSON
            configuration of the property, i.e. keyword arguments to the `__init__` method of the property class 
        """
        prop = self.get_type_from_name(**config)
        setattr(self.owner_cls, name, prop)
        prop.__set_name__(self.owner_cls, name)
        if prop.deepcopy_default:
            self._deep_copy_param_descriptor(prop)
            self._deep_copy_param_default(prop)
        self.clear()
       
    def clear(self):
        super().clear()
        self._instance_params = {}
        for attr in ['_db', '_db_init', '_db_persisting', '_remote']:
            try: 
                delattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}{attr}')
            except AttributeError:
                pass 

    @supports_only_instance_access("database operations are only supported at instance level")
    def get_from_DB(self) -> typing.Dict[str, typing.Any]:
        """
        get all properties (i.e. their values) currently stored in the database
        
        Returns
        -------
        Dict[str, typing.Any]
            dictionary of property names and their values
        """
        if not hasattr(self.owner_inst, 'db_engine'):
            raise AttributeError("database engine not set, this object is not connected to a database")
        props = self.owner_inst.db_engine.get_all_properties() # type: typing.Dict
        final_list = {}
        for name, prop in props.items():
            try:
                serializer = Serializers.for_object(self.owner_inst.id, self.owner_cls.__name__, name)
                final_list[name] = serializer.loads(prop)
            except Exception as ex:
                self.owner_inst.logger.error(
                    f"could not deserialize property {name} due to error - {str(ex)}, skipping this property"
                )
        return final_list

    @supports_only_instance_access("database operations are only supported at instance level")
    def load_from_DB(self):
        """
        Load and apply property values which have `db_init` or `db_persist` set to `True` from database
        """
        if not hasattr(self.owner_inst, 'db_engine'):
            return 
            # raise AttributeError("database engine not set, this object is not connected to a database")
        missing_properties = self.owner_inst.db_engine.create_missing_properties(
                                                                    self.db_init_objects,
                                                                    get_missing_property_names=True
                                                                )
        # 4. read db_init and db_persist objects
        with edit_constant_parameters(self):
            for db_prop, value in self.get_from_DB():
                try:
                    if db_prop not in missing_properties:
                        setattr(self.owner_inst, db_prop, value) # type: ignore
                except Exception as ex:
                    self.owner_inst.logger.error(f"could not set attribute {db_prop} due to error {str(ex)}")
    
    @classmethod
    def get_type_from_name(cls, name: str) -> typing.Type[Property]:
        return Property
    
    @supports_only_instance_access("additional property setup is required only for instances")
    def _setup_parameters(self, **parameters):
        """
        Initialize default and keyword parameter values.

        First, ensures that all Parameters with 'deepcopy_default=True'
        (typically used for mutable Parameters) are copied directly
        into each object, to ensure that there is an independent copy
        (to avoid surprising aliasing errors).  Then sets each of the
        keyword arguments, warning when any of them are not defined as
        parameters.

        Constant Parameters can be set during calls to this method.
        """
        ## Deepcopy all 'deepcopy_default=True' parameters
        # (building a set of names first to avoid redundantly
        # instantiating a later-overridden parent class's parameter)
        param_default_values_to_deepcopy = {}
        param_descriptors_to_deepcopy = {}
        for (k, v) in self.owner_cls.properties.descriptors.items():
            if v.deepcopy_default and k != "name":
                # (avoid replacing name with the default of None)
                param_default_values_to_deepcopy[k] = v
            if v.per_instance_descriptor and k != "name":
                param_descriptors_to_deepcopy[k] = v

        for p in param_default_values_to_deepcopy.values():
            self._deep_copy_param_default(p)
        for p in param_descriptors_to_deepcopy.values():
            self._deep_copy_param_descriptor(p)

        ## keyword arg setting
        if len(parameters) > 0:
            descs = self.descriptors
            for name, val in parameters.items():
                desc = descs.get(name, None) # pylint: disable-msg=E1101
                if desc:
                    setattr(self.owner_inst, name, val)
                # Its erroneous to set a non-descriptor (& non-param-descriptor) with a value from init. 
                # we dont know what that value even means, so we silently ignore

    @supports_only_instance_access("additional property setup is required only for instances")
    def _deep_copy_param_default(self, param_obj : 'Parameter') -> None:
        # deepcopy param_obj.default into self.__dict__ (or dict_ if supplied)
        # under the parameter's _internal_name (or key if supplied)
        _old = self.owner_inst.__dict__.get(param_obj._internal_name, NotImplemented) 
        _old = _old if _old is not NotImplemented else param_obj.default
        new_object = copy.deepcopy(_old)
        # remember : simply setting in the dict does not activate post setter and remaining logic which is sometimes important
        self.owner_inst.__dict__[param_obj._internal_name] = new_object

    @supports_only_instance_access("additional property setup is required only for instances")
    def _deep_copy_param_descriptor(self, param_obj : Parameter):
        param_obj_copy = copy.deepcopy(param_obj)
        self._instance_params[param_obj.name] = param_obj_copy
 

class ActionsRegistry(DescriptorRegistry):
    """
    A `DescriptorRegistry` for actions of a `Thing` class or `Thing` instance.
    """

    @property
    def descriptor_object(self) -> type[Action]:
        return Action
    
    descriptors = property(DescriptorRegistry.get_descriptors) # type: typing.Dict[str, Action]

    values = property(DescriptorRegistry._get_values, 
                    doc=DescriptorRegistry._get_values.__doc__) # type: typing.Dict[str, Action]  
                  
    def __getitem__(self, key: str) -> Action | BoundAction:
        return self.descriptors[key]
    
    def __contains__(self, action: Action | BoundAction) -> bool:
        return action in self.descriptors.values()
    
    
class EventsRegistry(DescriptorRegistry):
    """
    A `DescriptorRegistry` for events of a `Thing` class or `Thing` instance.
    """

    @property
    def descriptor_object(self):
        return Event

    descriptors = property(DescriptorRegistry.get_descriptors) # type: typing.Dict[str, Event]

    values = property(DescriptorRegistry._get_values, 
                    doc=DescriptorRegistry._get_values.__doc__) # type: typing.Dict[str, EventDispatcher]
    
    def __getitem__(self, key: str) -> Event | EventDispatcher:
        return self.descriptors[key]

    def __contains__(self, event: Event) -> bool:
        return event in self.descriptors.values()
    
    def clear(self):
        super().clear()
        for attr in ['_change_events', '_observables']:
            try: 
                delattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}{attr}')
            except AttributeError:
                pass
    
    @property
    def change_events(self) -> typing.Dict[str, Event]:
        """dictionary of change events of observable properties"""
        try:
            return getattr(self, f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_change_events')
        except AttributeError:
            change_events = dict()
            for name, evt in self.descriptors.items():
                if not evt._observable:
                    continue
                change_events[name] = evt
            setattr(
                self, 
                f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_change_events', 
                change_events
            )
            return change_events
    
    @property   
    def observables(self) -> typing.Dict[str, Property]:
        """dictionary of all properties that are observable, i.e. push change events"""
        try:
            return getattr(self, f'_{self._qualified__prefix}_{self.__class__.__name__.lower()}_observables')
        except AttributeError:
            props = dict()
            for name, prop in self.owner_cls.properties.descriptors.items():
                if not isinstance(prop, Property) or not prop._observable:
                    continue
                props[name] = prop
            setattr(
                self, 
                f'_{self._qualified_prefix}_{self.__class__.__name__.lower()}_observables', 
                props
            )
            return props



class Propertized(Parameterized):
    """
    Bae class providing additional functionality related to properties,
    like setting up a registry, allowing values to be set at `__init__()` etc. 
    It is not meant to be subclassed directly by the end-user.
    """

    # There is a word called Property+ize in english dictionary
    # https://en.wiktionary.org/wiki/propertization

    id : str

    # creating name without underscore causes clash with the metaclass method 
    # with same name
    def create_param_container(self, **params):
        self._properties_registry = PropertyRegistry(self.__class__, None, self)
        self._properties_registry._setup_parameters(**params)
        self._param_container = self._properties_registry # backwards compatibility with param

    @property
    def properties(self) -> PropertyRegistry:
        """container for the property descriptors of the object."""
        return self._properties_registry
    
    
class RemoteInvokable:
    """
    Base class providing additional functionality related to actions, 
    it is not meant to be subclassed directly by the end-user.
    """
    id : str
    
    def __init__(self):
        super().__init__()
        self.create_actions_registry()

    # creating name without underscore causes clash with the metaclass method 
    # with same name
    def create_actions_registry(self) -> None:
        """creates a registry for available `Actions` based on `ActionsRegistry`"""
        self._actions_registry = ActionsRegistry(self.__class__, self)

    @property
    def actions(self) -> ActionsRegistry:
        """container for the action descriptors of the object."""
        return self._actions_registry
    
   
class EventSource:
    """
    Base class to add event functionality to an object, 
    it is not meant to be subclassed directly by the end-user.
    """

    id : str

    def __init__(self) -> None:
        self._event_publisher = None # type: typing.Optional["EventPublisher"]
        self.create_events_registry()

    # creating name without underscore causes clash with the metaclass method 
    # with same name
    def create_events_registry(self) -> None:
        """creates a registry for available `Events` based on `EventsRegistry`"""
        self._events_registry = EventsRegistry(self.__class__, self)
        
    @property
    def events(self) -> EventsRegistry:
        """container for the event descriptors of the object."""
        return self._events_registry
            
    @property
    def event_publisher(self) -> "EventPublisher":
        """
        event publishing object `EventPublisher` that owns the zmq.PUB socket, valid only after 
        creating an RPC server or calling a `run()` method on the `Thing` instance.
        """
        return self._event_publisher 

    @event_publisher.setter           
    def event_publisher(self, value: "EventPublisher") -> None:
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



      
   