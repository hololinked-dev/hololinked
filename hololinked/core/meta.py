import copy
import inspect

from types import FunctionType
from typing import Any, KeysView, Type

from ..constants import JSON, JSONSerializable
from ..param.parameterized import EventDispatcher as ParamEventDispatcher
from ..param.parameterized import EventResolver as ParamEventResolver
from ..param.parameterized import Parameter, Parameterized, ParameterizedMetaclass
from ..param.parameterized import edit_constant as edit_constant_parameters
from ..utils import getattr_without_descriptor_read
from .actions import Action, BoundAction, action
from .events import Event, EventDispatcher, EventPublisher
from .property import Property


class ThingMeta(ParameterizedMetaclass):
    """
    Metaclass for `Thing`, implements a `__post_init__()` call and instantiation of a registry for properties', actions'
    and events' descriptor objects.
    Accessing properties, actions and events at the class level returns the descriptor object through the `DescriptorRegistry`
    implementation. Accessing properties, actions and events at instance level return their values (for example -
    the value of Property `foo` being `5`).
    `__post_init__()` is run after the user's `__init__()` method, properties that can be
    loaded from a database are loaded and written at this time. Overload `__post_init__()` in subclasses
    to add additional functionality.

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/Thing.pdf)
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
        creates `PropertiesRegistry` instead of `param`'s own `Parameters`
        as the default container for descriptors. All properties have definitions
        copied from `param`.
        """
        cls._param_container = PropertiesRegistry(cls, cls_members)

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
    def properties(cls) -> "PropertiesRegistry":
        """
        Container object for Property descriptors. Returns `PropertiesRegistry`
        instance instead of `param`'s own `Parameters` instance.
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

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/DescriptorRegistry.pdf)
    """

    def __init__(self, owner_cls: ThingMeta, owner_inst=None) -> None:
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
                prefix += f"_{self.owner_inst.id}"
            self._qualified__prefix = prefix
            return prefix

    @property
    def descriptor_object(self) -> Type[Property | Action | Event]:
        """The type of descriptor object that this registry holds, i.e. `Property`, `Action` or `Event`"""
        raise NotImplementedError("Implement descriptor_object in subclass")

    @property
    def descriptors(self) -> dict[str, Type[Property | Action | Event]]:
        """A dictionary with all the descriptors as values and their names as keys."""
        raise NotImplementedError("Implement descriptors in subclass")

    @property
    def names(self) -> KeysView[str]:
        """The names of the descriptors objects as a dictionary key view"""
        return self.descriptors.keys()

    @property
    def values(self) -> dict[str, Any]:
        """
        The values contained within the descriptors after reading when accessed at instance level, otherwise,
        the descriptor objects as dictionary when accessed at class level.
        """
        raise NotImplementedError("Implement values in subclass")

    def clear(self) -> None:
        """
        Deletes the descriptors dictionary (value of the `descriptors` property) so that it can be recreated.
        Does not delete the descriptors themselves. Call this method once if new descriptors are added to the
        class/instance dynamically in runtime.
        """
        for name in ["", "_values"]:
            try:
                delattr(
                    self,
                    f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}{name}",
                )
            except AttributeError:
                pass

    def __getitem__(self, key: str) -> Property | Action | Event:
        """Returns the descriptor object for the given key."""
        raise NotImplementedError("Implement __getitem__ in subclass")

    def __contains__(self, obj: Property | Action | Event) -> bool:
        """Returns `True` if the descriptor object is in the descriptors dictionary."""
        raise NotImplementedError("contains not implemented yet")

    def __dir__(self) -> list[str]:
        """Adds descriptor object to the dir"""
        return super().__dir__() + self.descriptors.keys()  # type: ignore

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

    def get_descriptors(self, recreate: bool = False) -> dict[str, Property | Action | Event]:
        """
        a dictionary with all the descriptors as values and their names as keys.

        Parameters
        ----------
        recreate: bool
            if `True`, the descriptors dictionary is recreated and returned, otherwise, the cached dictionary is returned.
        """
        if recreate:
            self.clear()
        try:
            return getattr(self, f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}")
        except AttributeError:
            descriptors = dict()
            for name, objekt in inspect._getmembers(
                self.owner_cls,
                lambda f: isinstance(f, self.descriptor_object),
                getattr_without_descriptor_read,
            ):
                descriptors[name] = objekt
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}",
                descriptors,
            )
            # We cache the parameters because this method is called often,
            # and parameters are rarely added (and cannot be deleted)
            return descriptors

    def get_values(self) -> dict[str, Any]:
        """
        the values contained within the descriptors after reading when accessed at instance level, otherwise,
        the descriptor objects as dictionary when accessed at class level.
        For example, if a `Thing` instance's property contains a value of 5, this method will return
        { property_name : 5 } when accessed at instance level, and { property_name : property_object } when accessed
        at class level.
        This method is also the getter of the `values` property.
        """
        if self.owner_inst is None:
            return self.descriptors
        try:
            return getattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_values",
            )
        except AttributeError:
            values = dict()
            for name, value in self.descriptors.items():
                values[name] = value.__get__(self.owner_inst, self.owner_cls)
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_values",
                values,
            )
            return values


def supports_only_instance_access(
    error_msg: str = "This method is only supported at instance level",
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


class PropertiesRegistry(DescriptorRegistry):
    """
    A `DescriptorRegistry` for properties of a `Thing` class or `Thing` instance.

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/DescriptorRegistry.pdf)
    """

    def __init__(self, owner_cls: ThingMeta, owner_class_members: dict, owner_inst=None):
        super().__init__(owner_cls, owner_inst)
        if self.owner_inst is None and owner_class_members is not None:
            # instantiated by class
            self.event_resolver = ParamEventResolver(owner_cls=owner_cls)
            self.event_dispatcher = ParamEventDispatcher(owner_cls, self.event_resolver)
            self.event_resolver.create_unresolved_watcher_info(owner_class_members)
        else:
            # instantiated by instance
            self._instance_params = {}
            self.event_resolver = self.owner_cls.properties.event_resolver
            self.event_dispatcher = ParamEventDispatcher(owner_inst, self.event_resolver)
            self.event_dispatcher.prepare_instance_dependencies()

    @property
    def descriptor_object(self) -> Type[Parameter]:
        return Parameter

    @property
    def descriptors(self) -> dict[str, Parameter]:
        if self.owner_inst is None:
            return super().get_descriptors()
        return dict(super().get_descriptors(), **self._instance_params)

    values = property(DescriptorRegistry.get_values, doc=DescriptorRegistry.get_values.__doc__)  # type: dict[str, Parameter | Property | Any]

    def __getitem__(self, key: str) -> Property | Parameter:
        return self.descriptors[key]

    def __contains__(self, value: str | Property | Parameter) -> bool:
        return value in self.descriptors.values() or value in self.descriptors

    @property
    def defaults(self) -> dict[str, Any]:
        """default values of all properties as a dictionary with property names as keys"""
        defaults = {}
        for key, val in self.descriptors.items():
            defaults[key] = val.default
        return defaults

    @property
    def remote_objects(self) -> dict[str, Property]:
        """
        dictionary of properties that are remotely accessible (`remote=True`),
        which is also a default setting for all properties
        """
        try:
            return getattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_remote",
            )
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
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_remote",
                remote_props,
            )
            return remote_props

    @property
    def db_objects(self) -> dict[str, Property]:
        """
        dictionary of properties that are stored or loaded from the database
        (`db_init`, `db_persist` or `db_commit` set to `True`)
        """
        try:
            return getattr(self, f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db")
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
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db",
                db_props,
            )
            return db_props

    @property
    def db_init_objects(self) -> dict[str, Property]:
        """dictionary of properties that are initialized from the database (`db_init` or `db_persist` set to `True`)"""
        try:
            return getattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_init",
            )
        except AttributeError:
            propdict = self.db_objects
            db_init_props = {}
            for name, desc in propdict.items():
                if desc.db_init or desc.db_persist:
                    db_init_props[name] = desc
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_init",
                db_init_props,
            )
            return db_init_props

    @property
    def db_commit_objects(self) -> dict[str, Property]:
        """dictionary of properties that are committed to the database (`db_commit` or `db_persist` set to `True`)"""
        try:
            return getattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_commit",
            )
        except AttributeError:
            propdict = self.db_objects
            db_commit_props = {}
            for name, desc in propdict.items():
                if desc.db_commit or desc.db_persist:
                    db_commit_props[name] = desc
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_commit",
                db_commit_props,
            )
            return db_commit_props

    @property
    def db_persisting_objects(self) -> dict[str, Property]:
        """dictionary of properties that are persisted through the database (`db_persist` set to `True`)"""
        try:
            return getattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_persisting",
            )
        except AttributeError:
            propdict = self.db_objects
            db_persisting_props = {}
            for name, desc in propdict.items():
                if desc.db_persist:
                    db_persisting_props[name] = desc
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_db_persisting",
                db_persisting_props,
            )
            return db_persisting_props

    def get(self, **kwargs) -> dict[str, Any]:
        """
        read properties from the object, implements WoT operations `readAllProperties` and `readMultipleProperties`

        Parameters
        ----------
        **kwargs: dict[str, Any]

            - names: `List[str]`
                list of property names to be fetched

            - or, key-value pairs of property
                name of the property to be fetched, along with a 'rename' for the property in the response.
                For example { 'foo_prop' : 'fooProp' } will return the property 'foo_prop' as 'fooProp' in the response.

        Returns
        -------
        dict[str, Any]
            dictionary of property names and their values

        Raises
        ------
        TypeError
            if property name is not a string or requested new name is not a string
        AttributeError
            if property does not exist or is not remote accessible
        """
        data = {}
        if len(kwargs) == 0:
            # read all properties
            for name, prop in self.remote_objects.items():
                if self.owner_inst is None and not prop.class_member:
                    continue
                data[name] = prop.__get__(self.owner_inst, self.owner_cls)
            return data
        elif "names" in kwargs:
            names = kwargs.get("names")
            if not isinstance(names, (list, tuple, str)):
                raise TypeError(
                    "Specify properties to be fetched as a list, tuple or comma separated names. "
                    + f"Given type {type(names)}"
                )
            if isinstance(names, str):
                names = names.split(",")
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

    def set(self, **values: dict[str, Any]) -> None:
        """
        set properties whose name is specified by keys of a dictionary; implements WoT operations `writeMultipleProperties`
        or `writeAllProperties`.

        Parameters
        ----------
        values: dict[str, Any]
            dictionary of property names and its new values

        Raises
        ------
        AttributeError
            if property does not exist or is not remote accessible
        """
        errors = ""
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
                errors += f"{name}: {str(ex)}\n"
        if errors:
            ex = RuntimeError(
                "Some properties could not be set due to errors. "
                + "Check exception notes or server logs for more information."
            )
            ex.__notes__ = errors
            raise ex from None

    def add(self, name: str, config: JSON) -> None:
        """
        add a property to the `Thing` object

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
        for attr in ["_db", "_db_init", "_db_persisting", "_remote"]:
            try:
                delattr(
                    self,
                    f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}{attr}",
                )
            except AttributeError:
                pass

    @supports_only_instance_access("database operations are only supported at instance level")
    def get_from_DB(self) -> dict[str, Any]:
        """
        get all properties (i.e. their values) currently stored in the database

        Returns
        -------
        dict[str, Any]
            dictionary of property names and their values
        """
        if not hasattr(self.owner_inst, "db_engine"):
            raise AttributeError("database engine not set, this object is not connected to a database")
        props = self.owner_inst.db_engine.get_all_properties()  # type: dict
        final_list = {}
        for name, prop in props.items():
            try:
                # serializer = Serializers.for_object(self.owner_inst.id, self.owner_cls.__name__, name)
                # if name in self.db_commit_objects:
                #     continue
                final_list[name] = prop
            except Exception as ex:
                self.owner_inst.logger.error(
                    f"could not deserialize property {name} due to error - {str(ex)}, skipping this property"
                )
        return final_list

    @supports_only_instance_access("database operations are only supported at instance level")
    def load_from_DB(self):
        """
        Load and apply property values from database which have `db_init` or `db_persist` set to `True`
        """
        if not hasattr(self.owner_inst, "db_engine"):
            return
            # raise AttributeError("database engine not set, this object is not connected to a database")
        missing_properties = self.owner_inst.db_engine.create_missing_properties(
            self.db_init_objects, get_missing_property_names=True
        )
        # 4. read db_init and db_persist objects
        with edit_constant_parameters(self.owner_inst):
            for db_prop, value in self.get_from_DB().items():
                try:
                    prop_desc = self.descriptors[db_prop]  # type: Property
                    if (prop_desc.db_init or prop_desc.db_persist) and db_prop not in missing_properties:
                        setattr(self.owner_inst, db_prop, value)  # type: ignore
                except Exception as ex:
                    self.owner_inst.logger.error(f"could not set attribute {db_prop} due to error {str(ex)}")

    @classmethod
    def get_type_from_name(cls, name: str) -> Type[Property]:
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
        for k, v in self.owner_cls.properties.descriptors.items():
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
                desc = descs.get(name, None)  # pylint: disable-msg=E1101
                if desc:
                    setattr(self.owner_inst, name, val)
                # Its erroneous to set a non-descriptor (& non-param-descriptor) with a value from init.
                # we dont know what that value even means, so we silently ignore

    @supports_only_instance_access("additional property setup is required only for instances")
    def _deep_copy_param_default(self, param_obj: "Parameter") -> None:
        # deepcopy param_obj.default into self.__dict__ (or dict_ if supplied)
        # under the parameter's _internal_name (or key if supplied)
        _old = self.owner_inst.__dict__.get(param_obj._internal_name, NotImplemented)
        _old = _old if _old is not NotImplemented else param_obj.default
        new_object = copy.deepcopy(_old)
        # remember : simply setting in the dict does not activate post setter and remaining logic which is sometimes important
        self.owner_inst.__dict__[param_obj._internal_name] = new_object

    @supports_only_instance_access("additional property setup is required only for instances")
    def _deep_copy_param_descriptor(self, param_obj: Parameter):
        param_obj_copy = copy.deepcopy(param_obj)
        self._instance_params[param_obj.name] = param_obj_copy


class ActionsRegistry(DescriptorRegistry):
    """
    A `DescriptorRegistry` for actions of a `Thing` class or `Thing` instance.

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/DescriptorRegistry.pdf)
    """

    @property
    def descriptor_object(self) -> Type[Action]:
        return Action

    descriptors = property(DescriptorRegistry.get_descriptors)  # type: dict[str, Action]

    values = property(DescriptorRegistry.get_values, doc=DescriptorRegistry.get_values.__doc__)  # type: dict[str, Action]

    def __getitem__(self, key: str) -> Action | BoundAction:
        if self.owner_inst is not None:
            return self.descriptors[key].__get__(self.owner_inst, self.owner_cls)
        return self.descriptors[key]

    def __contains__(self, action: str | Action | BoundAction) -> bool:
        return action in self.descriptors.values() or action in self.descriptors


class EventsRegistry(DescriptorRegistry):
    """
    A `DescriptorRegistry` for events of a `Thing` class or `Thing` instance.

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/DescriptorRegistry.pdf)
    """

    @property
    def descriptor_object(self):
        return Event

    descriptors = property(DescriptorRegistry.get_descriptors)  # type: dict[str, Event]

    values = property(DescriptorRegistry.get_values, doc=DescriptorRegistry.get_values.__doc__)  # type: dict[str, EventDispatcher]

    def __getitem__(self, key: str) -> Event | EventDispatcher:
        if self.owner_inst is not None:
            return self.descriptors[key].__get__(self.owner_inst, self.owner_cls)
        return self.descriptors[key]

    def __contains__(self, event: Event) -> bool:
        return event in self.descriptors.values() or event in self.descriptors

    def clear(self):
        super().clear()
        for attr in ["_change_events", "_observables"]:
            try:
                delattr(
                    self,
                    f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}{attr}",
                )
            except AttributeError:
                pass

    @property
    def plain(self) -> dict[str, Event]:
        """dictionary of events that are not change events (i.e., not observable)"""
        try:
            return getattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_non_change_events",
            )
        except AttributeError:
            non_change_events = dict()
            for name, evt in self.descriptors.items():
                if not evt._observable:
                    non_change_events[name] = evt
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_non_change_events",
                non_change_events,
            )
            return non_change_events

    @property
    def change_events(self) -> dict[str, Event]:
        """dictionary of change events belonging to observable properties"""
        try:
            return getattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_change_events",
            )
        except AttributeError:
            change_events = dict()
            for name, evt in self.descriptors.items():
                if not evt._observable:
                    continue
                change_events[name] = evt
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_change_events",
                change_events,
            )
            return change_events

    @property
    def observables(self) -> dict[str, Property]:
        """dictionary of all properties that are observable, i.e. that which push change events"""
        try:
            return getattr(
                self,
                f"_{self._qualified__prefix}_{self.__class__.__name__.lower()}_observables",
            )
        except AttributeError:
            props = dict()
            for name, prop in self.owner_cls.properties.descriptors.items():
                if not isinstance(prop, Property) or not prop.observable:
                    continue
                props[name] = prop
            setattr(
                self,
                f"_{self._qualified_prefix}_{self.__class__.__name__.lower()}_observables",
                props,
            )
            return props


class Propertized(Parameterized):
    """
    Base class providing additional functionality related to properties,
    like setting up a registry, allowing values to be set at `__init__()` etc.
    It is not meant to be subclassed directly by the end-user.

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/Thing.pdf)
    """

    # There is a word called Property+ize in english dictionary
    # https://en.wiktionary.org/wiki/propertization

    id: str

    # creating name without underscore causes clash with the metaclass method
    # with same name
    def create_param_container(self, **params):
        self._properties_registry = PropertiesRegistry(self.__class__, None, self)
        self._properties_registry._setup_parameters(**params)
        self._param_container = self._properties_registry  # backwards compatibility with param

    @property
    def properties(self) -> PropertiesRegistry:
        """container for the property descriptors of the object."""
        return self._properties_registry

    # we need to specification define it as an action to for the possibility of getting an
    # Affordance object associated with it i.e _get_properties.to_affordance() function needs to work.
    # TODO - fix this anomaly
    @action()
    def _get_properties(self, **kwargs) -> dict[str, Any]:
        """ """
        return self.properties.get(**kwargs)

    @action()
    def _set_properties(self, **values: dict[str, Any]) -> None:
        """
        set properties whose name is specified by keys of a dictionary

        Parameters
        ----------
        values: Dict[str, Any]
            dictionary of property names and its values
        """
        return self.properties.set(**values)  # returns None

    @action()
    def _get_properties_in_db(self) -> dict[str, JSONSerializable]:
        """
        get all properties in the database

        Returns
        -------
        Dict[str, JSONSerializable]
            dictionary of property names and their values
        """
        return self.properties.get_from_DB()

    @action()
    def _add_property(self, name: str, prop: JSON) -> None:
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


class RemoteInvokable:
    """
    Base class providing additional functionality related to actions,
    it is not meant to be subclassed directly by the end-user.

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/Thing.pdf)
    """

    id: str

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

    [UML Diagram](https://docs.hololinked.dev/UML/PDF/Thing.pdf)
    """

    id: str

    def __init__(self) -> None:
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
        try:
            return self.rpc_server.event_publisher if self.rpc_server else None
        except AttributeError:
            return None
