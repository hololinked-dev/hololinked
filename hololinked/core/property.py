from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Type

from pydantic import BaseModel, ConfigDict, RootModel, create_model

from ..param.parameterized import Parameter, Parameterized, ParameterizedMetaclass
from ..schema_validators import JSONSchemaValidator
from ..utils import issubklass
from .dataklasses import RemoteResourceInfoValidator
from .events import Event, EventDispatcher  # noqa: F401
from .exceptions import StateMachineError


class Property(Parameter):
    """
    get/set/delete an object/instance attribute with type definitions, validations, post-set effects, metadata and more.
    Please note the capital 'P' in `Property` to differentiate from python's own `property`.
    `Property` objects are similar to python's `property` but not a subclass of it due to limitations and redundancy.
    """

    __slots__ = [
        "db_persist",
        "db_init",
        "db_commit",
        "model",
        "metadata",
        "fcomparator",
        "validator",
        "execution_info",
        "_execution_info_validator",
        "_observable_event_descriptor",
        "_old_value_internal_name",
    ]

    def __init__(
        self,
        default: Any = None,
        *,
        doc: str | None = None,
        constant: bool = False,
        readonly: bool = False,
        allow_None: bool = False,
        label: str | None = None,
        state: list | tuple | str | Enum | None = None,
        db_persist: bool = False,
        db_init: bool = False,
        db_commit: bool = False,
        observable: bool = False,
        model: "BaseModel" | None = None,
        class_member: bool = False,
        fget: Callable | None = None,
        fset: Callable | None = None,
        fdel: Callable | None = None,
        fcomparator: Callable | None = None,
        deepcopy_default: bool = False,
        per_instance_descriptor: bool = False,
        remote: bool = True,
        precedence: float | None = None,
        metadata: dict | None = None,
    ) -> None:
        """
        Parameters
        ----------

        default: None or corresponding to property type
            The default value of the property.

        doc: str, default empty
            docstring explaining what this property represents.

        allow_None: bool, default `False`
            if `True`, None is accepted as a valid value in addition to any other values that are allowed.

        readonly: bool, default `False`
            if `True`, the value cannot be changed at all. Either the value is fetched always or a getter method
            is executed which may still generate dynamic values at each read/get operation.

        constant: bool, default `False`
            if `True`, the value can be changed only once when `allow_None` is set to `True`. The
            value is otherwise constant on the `Thing` instance.

        observable: bool, default `False`
            if `True`, pushes change events after every read and write if the value is different from the previous operation.
            Supply a function if interested to evaluate on what conditions the change event must be emitted.
            Default condition is a plain not-equal-to operator.

        state: str | Enum, default None
            state of state machine where property write can be executed

        db_persist: bool, default `False`
            if `True`, every write is stored in a database and the property value persists `Thing` instance destruction and
            recreation. The loaded value from database is written into the property at `Thing.__post_init__`.
            set `Thing.use_default_db` to `True`, to set up a default SQLite database or supply a `db_config_file`.

        db_init: bool, default `False`
            if `True`, property's first value is loaded from database and written using setter.
            Further writes are not written to database. Use this to load predetermined configuration which may change at
            a later time temporarily. if `db_persist` is `True`, this value is ignored.

        db_commit: bool,
            if `True`, all write values are stored to database. The database value is not loaded at `Thing.__post_init__()`.
            if db_persist is `True`, this value is ignored.

        fget: Callable, default None
            custom getter method, mandatory when setter method is also custom supplied.

        fset: Callable, default None
            custom setter method

        fdel: Callable, default None
            custom deleter method

        remote: bool, default `True`
            set to `False` to make the property local/not remotely accessible

        label: str, default extracted from object name
            optional text label to be used when this Property is shown in a listing. If no label is supplied,
            the attribute name for this property in the owning `Thing` object is used.

        metadata: dict, default None
            store your own metadata for the property which gives useful (and modifiable) information
            about the property. Properties operate using slots which means you cannot set foreign attributes on this object
            normally. This metadata dictionary should overcome this limitation.

        per_instance_descriptor: bool, default `False`
            whether a separate Property instance will be created for every `Thing` instance. `False` by default.
            If `False`, all instances of a `Thing` class will share the same Property object, including all validation
            attributes (bounds, allow_None etc.).

        deepcopy_default: bool, default `False`
            controls whether the default value of this Property will be deepcopied when a `Thing` object is instantiated (if
            `True`), or if the single default value will be shared by all `Thing` instances (if `False`). For an immutable
            Property value, it is best to leave deep_copy at the default of `False`. For a mutable Property value,
            for example - lists and dictionaries, the default of `False` is also appropriate if you want all instances to share
            the same value state, e.g. if they are each simply referring to a single global object like a singleton.
            If instead each `Thing` should have its own independently mutable value, deep_copy should be set to
            `True`. This setting is similar to using `field`'s `default_factory` in python dataclasses.

        class_member : bool, default `False`
            when `True`, property is set on `Thing` class instead of `Thing` instance.

        precedence: float, default None
            a numeric value, usually in the range 0.0 to 1.0, which allows the order of Properties in a class to be defined in
            a listing or e.g. in GUI menus. A negative precedence indicates a property that should be hidden in such listings.

        """
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
        self.execution_info = None  # RemoteResource | None
        if remote:
            # TODO, this execution info validator can be refactored & removed later, adds an additional layer of info
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

    def __set_name__(self, owner: Any, attrib_name: str) -> None:
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

    def __get__(self, obj: Parameterized, objtype: ParameterizedMetaclass) -> Any:
        read_value = super().__get__(obj, objtype)
        self.push_change_event(obj, read_value)
        return read_value

    def push_change_event(self, obj, value: Any) -> None:
        """
        Pushes change event both on read and write if an event publisher object is available
        on the owning `Thing`.

        Parameters
        ----------
        obj: Thing
            the `Thing` instance owning this property
        value: Any
            the value that was just read or written
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

    def validate_and_adapt(self, value) -> Any:
        """
        Validate the given value and adapt it if a proper logical reasoning can be given,
        for example, cropping a number to its bounds. Returns modified value.
        """
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

    def external_set(self, obj: Parameterized, value: Any) -> None:
        """
        method called when the value of the property is set from an external source, e.g. a remote client.
        Usually introduces a state machine check before allowing the set operation.
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

    def _post_value_set(self, obj, value: Any) -> None:
        if (self.db_persist or self.db_commit) and hasattr(obj, "db_engine"):
            obj.db_engine.set_property(self, value)
        self.push_change_event(obj, value)
        return super()._post_value_set(obj, value)

    def comparator(self, func: Callable) -> Callable:
        """
        Register a comparator method using this decorator to decide when to push
        a change event.

        Signature of the comparator method must be:
        ```
        def func(self, old_value, new_value) -> bool
        ```

        Parameters
        ----------
        func: Callable
            a method which takes two arguments - the old value and new value - and returns
            `True` if the values are considered different enough to push a change event.
            If the method is a classmethod, the first argument will be the owning class.
            If the method is a normal method, the first argument will be the owning instance.
            The second and third arguments will be the old and new values respectively.

        Returns
        -------
        Callable
            the supplied function, no modifications made but a reference is stored
        """
        self.fcomparator = func
        return func

    @property
    def is_remote(self):
        """`False` if the property is not remotely accessible"""
        return self._execution_info_validator is not None

    @property
    def observable(self) -> bool:
        """`True` if the property pushes change events on read and write"""
        return self._observable_event_descriptor is not None

    def to_affordance(self, owner_inst=None):
        """
        Generates a `PropertyAffordance` TD fragment for this Property

        Parameters
        ----------
        owner_inst: Thing, optional
            The instance of the owning `Thing` object. If not supplied, the class is used.

        Returns
        -------
        PropertyAffordance
            the affordance TD fragment for this property
        """
        from ..td import PropertyAffordance

        return PropertyAffordance.generate(self, owner_inst or self.owner)


class ModelRoot(RootModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


def wrap_plain_types_in_rootmodel(model: type) -> Type[BaseModel] | Type[RootModel]:
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
    return create_model(f"{model!r}", root=(model, ...), __base__=ModelRoot)  # type: ignore[call-overload]


__all__ = [Property.__name__]
