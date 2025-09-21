import typing
from enum import Enum

from ..param.parameterized import Parameter, Parameterized, ParameterizedMetaclass
from ..utils import issubklass
from ..exceptions import StateMachineError
from ..schema_validators import JSONSchemaValidator
from .dataklasses import RemoteResourceInfoValidator
from .events import Event, EventDispatcher  # noqa: F401


class Property(Parameter):
    """
    Initialize a new Property object and to get/set/delete an object/instance attribute. Please note the capital 'P' in
    Property to differentiate from python's own ``property``. ``Property`` objects are similar to python ``property``
    but not a subclass of it due to limitations and redundancy.

    Parameters
    ----------

    default: None or corresponding to property type
        The default value of the property.

    doc: str, default empty
        docstring explaining what this property represents.

    constant: bool, default False
        if True, the Property value can be changed only once when ``allow_None`` is set to True. The
        value is otherwise constant on the ``Thing`` instance.

    readonly: bool, default False
        if True, the Property value cannot be changed by setting the attribute at the class or instance
        levels at all. Either the value is fetched always or a getter method is executed which may still generate dynamic
        values at each get/read operation.

    allow_None: bool, default False
        if True, None is accepted as a valid value for this Property, in addition to any other values that are
        allowed.

    observable: bool, default False
        set to True to receive change events. Supply a function if interested to evaluate on what conditions the change
        event must be emitted. Default condition is a plain not-equal-to operator.

    state: str | Enum, default None
        state of state machine where property write can be executed

    db_persist: bool, default False
        if True, every write is stored in database and property value persists ``Thing`` instance destruction and creation.
        The loaded value from database is written into the property at ``Thing.__post_init__``.
        set ``Thing.use_default_db`` to True, to avoid setting up a database or supply a ``db_config_file``.

    db_init: bool, default False
        if True, property's first value is loaded from database and written using setter.
        Further writes are not written to database. if ``db_persist`` is True, this value is ignored.

    db_commit: bool,
        if True, all write values are stored to database. The database value is not loaded at ``Thing.__post_init__()``.
        if db_persist is True, this value is ignored.

    fget: Callable, default None
        custom getter method, mandatory when setter method is also custom supplied.

    fset: Callable, default None
        custom setter method

    fdel: Callable, default None
        custom deleter method

    remote: bool, default True
        set to false to make the property local/not remotely accessible

    label: str, default extracted from object name
        optional text label to be used when this Property is shown in a listing. If no label is supplied,
        the attribute name for this property in the owning ``Thing`` object is used.

    metadata: dict, default None
        store your own JSON compatible metadata for the property which gives useful (and modifiable) information
        about the property. Properties operate using slots which means you cannot set foreign attributes on this object
        normally. This metadata dictionary should overcome this limitation.

    per_instance_descriptor: bool, default False
        whether a separate Property instance will be created for every ``Thing`` instance. True by default.
        If False, all instances of a ```Thing``` class will share the same Property object, including all validation
        attributes (bounds, allow_None etc.).

    deepcopy_default: bool, default False
        controls whether the default value of this Property will be deepcopied when a ``Thing`` object is instantiated (if
        True), or if the single default value will be shared by all ``Thing`` instances (if False). For an immutable
        Property value, it is best to leave deep_copy at the default of False. For a mutable Property value,
        for example - lists and dictionaries, the default of False is also appropriate if you want all instances to share
        the same value state, e.g. if they are each simply referring to a single global object like a singleton.
        If instead each ``Thing`` should have its own independently mutable value, deep_copy should be set to
        True. This setting is similar to using ``field``'s ``default_factory`` in python dataclasses.

    class_member : bool, default False
        when True, property is set on ``Thing`` class instead of ``Thing`` instance.

    precedence: float, default None
        a numeric value, usually in the range 0.0 to 1.0, which allows the order of Properties in a class to be defined in
        a listing or e.g. in GUI menus. A negative precedence indicates a property that should be hidden in such listings.

    """

    __slots__ = [
        "db_persist",
        "db_init",
        "db_commit",
        "model",
        "metadata",
        "_execution_info_validator",
        "execution_info",
        "_observable_event_descriptor",
        "fcomparator",
        "_old_value_internal_name",
        "validator",
    ]

    def __init__(
        self,
        default: typing.Any = None,
        *,
        doc: typing.Optional[str] = None,
        constant: bool = False,
        readonly: bool = False,
        allow_None: bool = False,
        label: typing.Optional[str] = None,
        state: typing.Optional[typing.Union[typing.List, typing.Tuple, str, Enum]] = None,
        db_persist: bool = False,
        db_init: bool = False,
        db_commit: bool = False,
        observable: bool = False,
        model: typing.Optional["BaseModel"] = None,
        class_member: bool = False,
        fget: typing.Optional[typing.Callable] = None,
        fset: typing.Optional[typing.Callable] = None,
        fdel: typing.Optional[typing.Callable] = None,
        fcomparator: typing.Optional[typing.Callable] = None,
        deepcopy_default: bool = False,
        per_instance_descriptor: bool = False,
        remote: bool = True,
        precedence: typing.Optional[float] = None,
        metadata: typing.Optional[typing.Dict] = None,
    ) -> None:
        super().__init__(
            default=default,
            doc=doc,
            constant=constant,
            readonly=readonly,
            allow_None=allow_None,
            label=label,
            per_instance_descriptor=per_instance_descriptor,
            deepcopy_default=deepcopy_default,
            class_member=class_member,
            fget=fget,
            fset=fset,
            fdel=fdel,
            precedence=precedence,
        )
        self.db_persist = db_persist
        self.db_init = db_init
        self.db_commit = db_commit
        self.fcomparator = fcomparator
        self.metadata = metadata
        self._observable_event_descriptor = None
        if observable:
            self._observable_event_descriptor = Event()
        self._execution_info_validator = None
        self.execution_info = None  # typing.Optional[RemoteResource]
        if remote:
            self._execution_info_validator = RemoteResourceInfoValidator(state=state, isproperty=True, obj=self)
            self.execution_info = self._execution_info_validator  # TODO: use dataclass or remove this attribute
        self.model = None
        self.validator = None
        if model:
            if isinstance(model, dict):
                self.model = model
                self.validator = JSONSchemaValidator(model).validate
            else:
                self.model = wrap_plain_types_in_rootmodel(model)  # type: BaseModel
                self.validator = self.model.model_validate

    def __set_name__(self, owner: typing.Any, attrib_name: str) -> None:
        super().__set_name__(owner, attrib_name)
        if self._execution_info_validator:
            self._execution_info_validator.obj_name = attrib_name
        if self._observable_event_descriptor:
            _observable_event_name = f"{self.name}_change_event"
            self._old_value_internal_name = f"{self._internal_name}_old_value"
            self._observable_event_descriptor.doc = f"change event for {self.name}"
            self._observable_event_descriptor._observable = True
            self._observable_event_descriptor.__set_name__(owner, _observable_event_name)
            # This is a descriptor object, so we need to set it on the owner class
            setattr(owner, _observable_event_name, self._observable_event_descriptor)

    def __get__(self, obj: Parameterized, objtype: ParameterizedMetaclass) -> typing.Any:
        read_value = super().__get__(obj, objtype)
        self.push_change_event(obj, read_value)
        return read_value

    def push_change_event(self, obj, value: typing.Any) -> None:
        """
        Pushes change event both on read and write if an event publisher object is available
        on the owning Thing.
        """
        if obj is None:
            return
        if self._observable_event_descriptor and obj.event_publisher:
            event_dispatcher = getattr(obj, self._observable_event_descriptor.name, None)  # type: EventDispatcher
            old_value = obj.__dict__.get(self._old_value_internal_name, NotImplemented)
            obj.__dict__[self._old_value_internal_name] = value
            if self.fcomparator:
                if issubklass(self.fcomparator, classmethod):
                    if not self.fcomparator(self.owner, old_value, value):
                        return
                elif not self.fcomparator(obj, old_value, value):
                    return
            elif not old_value != value:
                return
            event_dispatcher.push(value)

    def validate_and_adapt(self, value) -> typing.Any:
        if value is None:
            if self.allow_None:
                return
            else:
                raise ValueError(f"Property {self.name} does not allow None values")
        if self.model:
            if isinstance(self.model, dict):
                self.validator(value)
            elif issubklass(self.model, RootModel):
                value = self.model(value)
            elif issubklass(self.model, BaseModel):
                value = self.model(**value)
        return super().validate_and_adapt(value)

    def external_set(self, obj: Parameterized, value: typing.Any) -> None:
        """
        Set the value of the property from an external source, e.g. a remote client.
        """
        if self.execution_info.state is None or (
            hasattr(obj, "state_machine") and obj.state_machine.current_state in self.execution_info.state
        ):
            return self.__set__(obj, value)
        else:
            raise StateMachineError(
                "Thing {} is in `{}` state, however attribute can be written only in `{}` state".format(
                    obj.id, obj.state_machine.current_state, self.execution_info.state
                )
            )

    def _post_value_set(self, obj, value: typing.Any) -> None:
        if (self.db_persist or self.db_commit) and hasattr(obj, "db_engine"):
            from .thing import Thing

            assert isinstance(obj, Thing), (
                f"database property {self.name} bound to a non Thing, currently not supported"
            )
            obj.db_engine.set_property(self, value)
        self.push_change_event(obj, value)
        return super()._post_value_set(obj, value)

    def comparator(self, func: typing.Callable) -> typing.Callable:
        """
        Register a comparator method by using this as a decorator to decide when to push
        a change event.
        """
        self.fcomparator = func
        return func

    @property
    def is_remote(self):
        """Returns False if the property is not remotely accessible, i.e. it is not a RemoteResource."""
        return self._execution_info_validator is not None

    @property
    def observable(self) -> bool:
        """Returns True if the property is observable, i.e. it has an event descriptor."""
        return self._observable_event_descriptor is not None

    def to_affordance(self, owner_inst=None):
        from ..td import PropertyAffordance

        return PropertyAffordance.generate(self, owner_inst or self.owner)


try:
    from pydantic import BaseModel, RootModel, create_model

    def wrap_plain_types_in_rootmodel(model: type) -> type[BaseModel] | type[RootModel]:
        """
        Ensure a type is a subclass of BaseModel.

        If a `BaseModel` subclass is passed to this function, we will pass it
        through unchanged. Otherwise, we wrap the type in a RootModel.
        In the future, we may explicitly check that the argument is a type
        and not a model instance.
        """
        if model is None:
            return
        if issubklass(model, BaseModel):
            return model
        return create_model(f"{model!r}", root=(model, ...), __base__=RootModel)
except ImportError:

    def wrap_plain_types_in_rootmodel(model: type) -> type:
        raise ImportError("pydantic is not installed, please install it to use this feature") from None


__all__ = [Property.__name__]
