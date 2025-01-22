
import inspect
import typing

from ..param.parameterized import (ClassParameters, InstanceParameters, Parameterized, ParameterizedMetaclass,
                            edit_constant as edit_constant_parameters)
from ..utils import getattr_without_descriptor_read
from ..constants import JSON, JSONSerializable
from .actions import Action, BoundAction
from .property import Property
from .events import Event, EventPublisher



class ThingMeta(ParameterizedMetaclass):
    """
    Metaclass for Thing, implements a `__post_init__()` call and instantiation of a container for properties', actions'
    and events' descriptor objects. During instantiation of `Thing`, first loggers and database connection 
    are created, after which the user `__init__` is called. In `__post_init__()`, that runs after user's `__init__()`, 
    the exposed resources 
    are segregated while accounting for any `Event` objects or instance specific properties created during init. Properties 
    are also loaded from database at this time. One can overload `__post_init__()` for any operations that rely on properties
    values loaded from database.
    """
    def __init__(mcs, name, bases, dict_):
        super().__init__(name, bases, dict_)
        mcs._create_actions_container()
        mcs._create_events_container()

    def __call__(mcls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        instance.__post_init__()
        return instance
    
    def _create_param_container(cls, cls_members: dict) -> None:
        """
        creates `ClassProperties` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All properties have definitions 
        copied from `param`.
        """
        cls._param_container = ClassProperties(cls, cls_members)

    def _create_actions_container(cls) -> None:
        """
        creates `Actions` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All actions have definitions 
        copied from `param`.
        """
        cls._actions_registry = ActionsRegistry(cls)

    def _create_events_container(cls) -> None:
        """
        creates `Events` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All events have definitions 
        copied from `param`.
        """
        cls._events_registry = EventsRegistry(cls)

    @property
    def properties(cls) -> "ClassProperties":
        """
        Container object for Property descriptors. Returns `ClassProperties` instance instead of `param`'s own 
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
       


   
class ClassProperties(ClassParameters):
    """
    Object that holds the namespace and implementation of Parameterized methods as well as any state that is not 
    in __slots__ or the Properties themselves.
    Exists at metaclass level (instantiated by the metaclass). Contains state specific to the class.
    """
    @property
    def remote_objects(self) -> typing.Dict[str, Property]:
        """Dictionary of properties that are remotely accessible"""
        try:
            return getattr(self.owner_cls, f'_{self.owner_cls.__name__}_remote_params')
        except AttributeError: 
            paramdict = super().descriptors
            remote_params = {}
            for name, desc in paramdict.items():
                if isinstance(desc, Property):
                    remote_params[name] = desc
            setattr(self.owner_cls, f'_{self.owner_cls.__name__}_remote_params', remote_params)
        return getattr(self.owner_cls, f'_{self.owner_cls.__name__}_remote_params')
    
    @property
    def db_persisting_objects(self):
        try:
            return getattr(self.owner_cls, f'_{self.owner_cls.__name__}_db_persisting_remote_params')
        except AttributeError: 
            paramdict = self.remote_objects
            db_persisting_remote_params = {}
            for name, desc in paramdict.items():
                if desc.db_persist:
                    db_persisting_remote_params[name] = desc
            setattr(self.owner_cls, f'_{self.owner_cls.__name__}_db_persisting_remote_params', db_persisting_remote_params)
        return getattr(self.owner_cls, f'_{self.owner_cls.__name__}_db_persisting_remote_params')

    @property
    def db_init_objects(self) -> typing.Dict[str, Property]:
        try:
            return getattr(self.owner_cls, f'_{self.owner_cls.__name__}_db_init_remote_params')
        except AttributeError: 
            paramdict = self.remote_objects
            init_load_params = {}
            for name, desc in paramdict.items():
                if desc.db_init or desc.db_persist:
                    init_load_params[name] = desc
            setattr(self.owner_cls, f'_{self.owner_cls.__name__}_db_init_remote_params', init_load_params)
        return getattr(self.owner_cls, f'_{self.owner_cls.__name__}_db_init_remote_params')
        

class InstanceProperties(ClassProperties, InstanceParameters):
    
    def get(self, **kwargs) -> typing.Dict[str, typing.Any]:
        """
        """
        skip_props = ["zmq_resources", "GUI", "object_info"]
        for prop_name in skip_props:
            if prop_name in kwargs:
                raise RuntimeError("GUI, httpserver resources, RPC resources , object info etc. cannot be queried" + 
                                  " using multiple property fetch.")
        data = {}
        if len(kwargs) == 0:
            for name, prop in self.properties.descriptors.items():
                if name in skip_props or not isinstance(prop, Property):
                    continue
                if not prop.remote:
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
                if not isinstance(self.properties[requested_prop], Property) or self.properties[requested_prop].remote is None:
                    raise AttributeError("this property is not remote accessible")
                data[requested_prop] = self.properties[requested_prop].__get__(self, type(self))
        elif len(kwargs.keys()) != 0:
            for rename, requested_prop in kwargs.items():
                if not isinstance(self.properties[requested_prop], Property) or self.properties[requested_prop].remote is None:
                    raise AttributeError("this property is not remote accessible")
                data[rename] = self.properties[requested_prop].__get__(self, type(self))                   
        return data 
    
   
    def set(self, **values : typing.Dict[str, typing.Any]) -> None:
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
        

    def add(self, name : str, prop : JSON) -> None:
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

    
    def get_from_db(self) -> typing.Dict[str, JSONSerializable]:
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

    
    def load_from_DB(self):
        """
        Load and apply property values which have `db_init` or `db_persist`
        set to `True` from database
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

 

class DescriptorRegistry:
    """
    A registry for descriptors of a class or instance. Each of properties, actions and events subclasss from here 
    to implement a registry of their available objects. 
    """

    def __init__(self, owner_cls: ThingMeta, owner_inst) -> None:
        super().__init__()
        self.owner_cls = owner_cls
        self.owner_inst = owner_inst

    @property
    def owner(self):
        return self.owner_inst if self.owner_inst is not None else self.owner_cls#
    
    @property   
    def qualified_prefix(self) -> str:
        try: 
            self._qualified_prefix
        except AttributeError:
            prefix = self.owner_cls.__name__.lower()
            if self.owner_inst is not None:
                prefix += f'_{self.owner_inst.id}'
            self._qualified_prefix = prefix
            return prefix
    
    @property
    def descriptor_object(self):
        raise NotImplementedError("Implement descriptor_object in subclass")

    def __getitem__(self, key: str):
        raise NotImplementedError("Implement __getitem__ in subclass")
    
    def __contains__(self, obj: typing.Any) -> bool:
        raise NotImplementedError("contains not implemented yet")
    
    def __dir__(self) -> typing.List[str]:
        """Adds descriptor object to the dir"""
        return super().__dir__() + self.descriptors().keys() # type: ignore
    
    def __iter__(self):
        """Iterates over the descriptors of this object."""
        yield from self.descriptors

    def __len__(self) -> int:
        return len(self.descriptors)
    
    @property
    def names(self) -> typing.Iterable[str]:
        return self.descriptors.keys()

    @property
    def descriptors(self):
        raise NotImplementedError("Implement descriptors in subclass")
    
    def _get_descriptors(self) -> typing.Dict[str, Property | Action | Event]:
        """
        a dictionary with all the properties of the object as values (methods that are decorated with `property`) and 
        their names as keys.
        """
        try:
            return getattr(self, f'_{self.qualified_prefix}_{self.__class__.__name__.lower()}')
        except AttributeError:
            descriptors = dict()
            for name, objekt in inspect._getmembers(
                        self.owner_cls, 
                        lambda f: isinstance(f, self.descriptor_object),
                        getattr_without_descriptor_read
                    ): 
                descriptors[name] = objekt
            setattr(self.owner, f'_{self.qualified_prefix}_{self.__class__.__name__.lower()}', descriptors)
            return descriptors
        
    
    def _items(self) -> typing.Iterable[Property | Action | Event]:
        if self.owner_inst is None:
            raise AttributeError("Cannot get items of class level descriptors")
        return self.descriptors.items()
    
  
class ActionsRegistry(DescriptorRegistry):

    @property
    def descriptor_object(self) -> type[Action]:
        return Action
    
    descriptors = property(DescriptorRegistry._get_descriptors) # type: typing.Dict[str, Action]

    items = property(DescriptorRegistry._items) # type: typing.Iterable[BoundAction]

    def __getitem__(self, key: str) -> Action | BoundAction:
        """
        Returns the class or instance parameter like a dictionary dict[key] syntax lookup
        """
        # code change comment -
        # metaclass instance has a param attribute remember, no need to repeat logic of self_.self_or_cls
        # as we create only one instance of Parameters object 
        return self.descriptors[key] # if self.owner_inst is None else self.owner_inst.param.objects(False)
    
    def __contains__(self, action: Action | BoundAction) -> bool:
        if self.owner == self.owner_cls:
            return action in self.descriptors.values()
        return action in self.descriptors.values()

    
class EventsRegistry(DescriptorRegistry):

    @property
    def descriptor_object(self):
        return Event

    descriptors = property(DescriptorRegistry._get_descriptors) # type: typing.Dict[str, Event]

    items = property(DescriptorRegistry._items) # type: typing.Iterable[Event]

    def __getitem__(self, key: str) -> Event:
        return self.descriptors[key]

    def __contains__(self, event: Event) -> bool:
        return event in self.descriptors.values()
    
    @property
    def change_events(self) -> typing.Dict[str, Event]:
        try:
            return getattr(self, f'_{self.id}_change_events')
        except AttributeError:
            change_events = dict()
            for name, evt in self.descriptors.items():
                assert isinstance(evt, Event), "object is not an event"
                if not evt._observable:
                    continue
                change_events[name] = evt
            setattr(self, f'_{self.qualified_prefix}_change_events', change_events)
            return change_events
    
    @property   
    def observables(self):
        raise NotImplementedError("observables property not implemented yet")


class Propertized(Parameterized):

    # There is a word called Property+ize in english dictionary
    # https://en.wiktionary.org/wiki/propertization

    id : str

    def create_param_container(self, **params):
        self._param_container = InstanceProperties(self.__class__, self)
        self._param_container._setup_parameters(**params)
        self._properties_container = self._param_container


class RemoteInvokable:
    """
    Base class providing additional functionality related to actions, 
    it is not meant to be subclassed directly by the end-user.
    """
    id : str
    
    def __init__(self):
        super().__init__()
        self._create_actions_container()

    def _create_actions_container(self) -> None:
        """
        creates `Actions` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All actions have definitions 
        copied from `param`.
        """
        self._actions_registry = ActionsRegistry(self.__class__, self)


class EventSource:
    """Class to add event functionality to the object"""

    id : str

    def __init__(self) -> None:
        self._event_publisher = None # type : typing.Optional["EventPublisher"]
        self._create_events_container()

    def _create_events_container(self) -> None:
        """
        creates `Events` instead of `param`'s own `Parameters` 
        as the default container for descriptors. All events have definitions 
        copied from `param`.
        """
        self._events_registry = EventsRegistry(self.__class__, self)
        
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



      
   