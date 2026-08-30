"""Concrete definition of an Action. Implemention of async and sync versions, action decorator."""

from __future__ import annotations

import warnings

from collections.abc import Callable
from enum import Enum
from inspect import getfullargspec, iscoroutinefunction
from types import FunctionType, MethodType
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, RootModel

from hololinked import SchemaValidators
from hololinked.config import global_config
from hololinked.constants import JSON
from hololinked.core.exceptions import StateMachineError
from hololinked.core.interfaces.metadata import ActionMetadata
from hololinked.param.parameterized import ParameterizedFunction
from hololinked.param.parameters import Tuple
from hololinked.utils import (
    get_input_model_from_signature,
    get_return_type_from_signature,
    has_async_def,
    isclassmethod,
    issubklass,
)


if TYPE_CHECKING:
    from hololinked.core.interfaces import ActionMetadata, BaseSchemaValidator
    from hololinked.core.meta import ThingMeta
    from hololinked.core.thing import Thing


class Action:
    """
    Object that models an action.

    These actions are unbound and return a bound action when accessed using the owning object.
    """

    __slots__ = [
        "_schema_validator",
        "argument_schema",
        "create_task",
        "idempotent",
        "isclassmethod",
        "iscoroutine",
        "isparameterized",
        "obj",
        "owner",
        "request_as_argument",
        "return_value_schema",
        "safe",
        "state",
        "synchronous",
    ]

    state: tuple[Enum | str] | None
    """state machine state(s) in which this action can be executed, any state when None"""

    def __init__(self, obj: MethodType) -> None:
        """
        Initialize an Action.

        Parameters
        ----------
        obj: MethodType
            the method that is being wrapped as an action
        """
        self.obj = obj
        self.state = None
        self.iscoroutine = False
        self.isclassmethod = False
        self.isparameterized = False
        self.request_as_argument = False
        self.create_task = False
        self.safe = False
        self.idempotent = False
        self.synchronous = True
        self.argument_schema = None
        self.return_value_schema = None
        self._schema_validator = None

    def __set_name__(self, owner, name):
        self.owner = owner

    def __str__(self) -> str:
        return f"<Action({self.owner.__name__}.{self.obj.__name__})>"

    def __eq__(self, other) -> bool:
        if not isinstance(other, Action):
            return False
        return self.obj == other.obj

    def __hash__(self) -> int:
        return hash(self.obj)

    def __get__(self, instance, owner):
        if instance is None and not self.isclassmethod:
            return self
        if self.iscoroutine:
            return BoundAsyncAction(self.obj, self, instance, owner)
        return BoundSyncAction(self.obj, self, instance, owner)

    def __call__(self, *args, **kwargs):
        raise NotImplementedError(
            f"Cannot invoke unbound action {self.name} of {self.owner.__name__}."
            + " Bound methods must be called, not the action itself. Use the appropriate instance to call the method."
        )

    @property
    def name(self) -> str:
        """Name of the action."""
        return self.obj.__name__

    @property
    def schema_validator(self) -> BaseSchemaValidator | None:
        """
        Validator for the arguments of this action, None if the action has no validation.

        Built from `argument_schema` the first time it is needed, which is when the action is first invoked.
        Further calls return the cached instance.
        """
        if self._schema_validator is None and self.argument_schema:
            self._schema_validator = SchemaValidators.for_schema(self.argument_schema)(self.argument_schema)
        return self._schema_validator

    def to_metadata(self, owner_inst: Thing | ThingMeta | None = None, format: str = "wot") -> ActionMetadata:
        """
        Generates a `ActionAffordance` TD fragment for this Action.

        Parameters
        ----------
        owner_inst: Thing, optional
            The instance of the owning `Thing` object. If not supplied, the class is used.

        Returns
        -------
        ActionAffordance
            the affordance TD fragment for this action
        """
        from hololinked.ddl import MetadataFormats

        return MetadataFormats.get(format).action.from_descriptor(
            self,
            owner_inst or self.owner,
        )


class BoundAction:
    """A bound action, base class for both sync and async methods."""

    obj: FunctionType | MethodType

    __slots__ = [
        "action",
        "bound_obj",
        "obj",
        "owner",
        "owner_inst",
    ]

    def __init__(self, obj: FunctionType | MethodType, descriptor: Action, owner_inst, owner) -> None:
        self.obj = obj
        self.action = descriptor
        self.owner = owner
        self.owner_inst = owner_inst
        self.bound_obj = owner if descriptor.isclassmethod else owner_inst

    @property
    def descriptor(self) -> Action:
        """The action descriptor."""
        return self.action

    def __post_init__(self):
        # never called, neither possible to call, only type hinting
        # owner class and instance
        self.owner: ThingMeta
        self.owner_inst: Thing
        self.obj: FunctionType
        self.action: Action

    def validate_call(self, args, kwargs: dict[str, Any]) -> None:
        """
        Validate the call to the action, like payload, state machine state etc.

        Errors are raised as exceptions.

        Parameters
        ----------
        args: tuple
            positional arguments to the action
        kwargs: dict
            keyword arguments to the action

        Raises
        ------
        StateMachineError
            if the action cannot be executed in the current state of the owning thing
        RuntimeError
            if the action explicity accepts only keyword arguments but some positional arguments are given
        """
        if self.action.isparameterized and len(args) > 0:
            raise RuntimeError("parameterized functions cannot have positional arguments")
        if self.owner_inst is None:
            return
        if self.action.state is None or (
            hasattr(self.owner_inst, "state_machine")
            and self.owner_inst.state_machine.current_state in self.action.state  # ty: ignore[unresolved-attribute]
        ):
            if self.action.schema_validator is not None:
                self.action.schema_validator.validate_method_call(args, kwargs)
        else:
            raise StateMachineError(
                f"Thing '{self.owner_inst}' is in '{self.owner_inst.state}' state, however action can be executed only in '{self.action.state}' state"
            )

    @property
    def name(self) -> str:
        """Name of the action."""
        return self.obj.__name__

    def __call__(self, *args, **kwargs):
        raise NotImplementedError("call must be implemented by subclass")

    def external_call(self, *args, **kwargs):
        """
        Validated call to the action with state machine and payload checks.

        Returns
        -------
        Any
            the return value of the action
        """
        raise NotImplementedError("external_call must be implemented by subclass")

    def __str__(self):
        return f"<BoundAction({self.owner.__name__}.{self.obj.__name__} of {self.owner_inst.id})>"

    def __eq__(self, value):
        if not isinstance(value, BoundAction):
            return False
        return self.obj == value.obj

    def __hash__(self):
        return hash(str(self))

    def __getattribute__(self, name):
        # https://docs.python.org/3/howto/descriptor.html#functions-and-methods
        if name == "__doc__":
            return self.obj.__doc__
        return super().__getattribute__(name)

    def to_metadata(self, owner_inst: Thing | ThingMeta | None = None, format: str = "wot") -> ActionMetadata:
        """
        Generates a `ActionAffordance` TD fragment for this Action.

        Parameters
        ----------
        owner_inst: Thing, optional
            The instance of the owning `Thing` object. If not supplied, the class is used.

        Returns
        -------
        ActionAffordance
            the affordance TD fragment for this action
        """
        return Action.to_metadata(self.descriptor, owner_inst or self.owner_inst or self.owner, format=format)


class BoundSyncAction(BoundAction):
    """
    Non-async(io) action call.

    The call is passed to the method as-it-is to allow local
    invocation without state machine checks. Use `external_call` to have validation.
    """

    def external_call(self, *args, **kwargs):
        """
        Validated call to the action with state machine and payload checks.

        Returns
        -------
        Any
            the return value of the action
        """
        self.validate_call(args, kwargs)
        return self.__call__(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        if self.action.isclassmethod:
            return self.obj(*args, **kwargs)
        return self.obj(self.bound_obj, *args, **kwargs)


class BoundAsyncAction(BoundAction):
    """
    async(io) action call.

    The call is passed to the method as-it-is to allow local
    invocation without state machine checks. Use `external_call` to have validation.
    """

    async def external_call(self, *args, **kwargs):
        """
        Validated call to the action with state machine and payload checks.

        Returns
        -------
        Any
            the return value of the action
        """
        self.validate_call(args, kwargs)
        return await self.__call__(*args, **kwargs)

    async def __call__(self, *args, **kwargs):
        if self.action.isclassmethod:
            return await self.obj(*args, **kwargs)
        return await self.obj(self.bound_obj, *args, **kwargs)


__action_kw_arguments__ = ["safe", "idempotent", "synchronous"]


def action(
    input_schema: JSON | BaseModel | RootModel | None = None,
    output_schema: JSON | BaseModel | RootModel | None = None,
    state: str | Enum | None = None,
    **kwargs,
) -> Callable[[Any], Action]:
    """
    Decorate on your methods to make them accessible remotely or create 'actions' out of them.

    When used with hardware, actions generally command the hardware to do something.

    Parameters
    ----------
    input_schema: JSON | BaseModel | RootModel, optional
        schema for arguments to validate
    output_schema: JSON | BaseModel | RootModel, optional
        schema for return value, currently only used to inform clients which are supposed to validate on their own
    state: str | Tuple[str], optional
        state machine state under which the action can be executed. When not provided, the action can be executed
        under any state.
    **kwargs:
        additional keyword arguments to specify action characteristics:

        - `synchronous`: bool,
            indicate in thing description if action is synchronous (not long running/threaded or async) - completes
            in a deterministic (& usually) short period of time, default `True`
        - `threaded`: bool,
            indicate that a method/action should be run in a separate thread, default `False`.
            Alternative to `synchronous` for non-async methods.
        - `create_task`: bool,
            indicate that a method/action should be run in a new task, default `True`.
            Alternative to `synchronous` for async methods.
        - `safe`: bool,
            indicate in thing description if action is safe to execute, default `False`
        - `idempotent`: bool,
            indicate in thing description if action is idempotent (for example, allows HTTP clients to cache return value),
            default `False`

    Returns
    -------
    Action
        returns the callable object wrapped in an `Action` object. When accessed at instance level,
        a `BoundSyncAction` or `BoundAsyncAction` object is returned.

    Raises
    ------
    TypeError
        if the decorated object is not a function or method, or if the input/output schema is of invalid type
    ValueError
        if the decorated function is a dunder method, or if unknown keyword arguments are provided
    """

    def inner(obj):
        input_schema = inner._arguments.get("input_schema", None)  # ty: ignore[unresolved-attribute]
        output_schema = inner._arguments.get("output_schema", None)  # ty: ignore[unresolved-attribute]
        state = inner._arguments.get("state", None)  # ty: ignore[unresolved-attribute]
        kwargs = inner._arguments.get("kwargs", {})  # ty: ignore[unresolved-attribute]

        original = obj
        if (
            not isinstance(obj, (FunctionType, MethodType, Action, BoundAction))
            and not isclassmethod(obj)
            and not issubklass(obj, ParameterizedFunction)
        ):
            raise TypeError(f"target for action or is not a function/method. Given type {type(obj)}") from None
        if isclassmethod(obj):
            obj = obj.__func__
        if isinstance(obj, (Action, BoundAction)):
            if (obj if isinstance(obj, Action) else obj.action).isclassmethod:
                raise RuntimeError("cannot wrap a classmethod as action once again, please skip")
            warnings.warn(
                f"{obj.name} is already wrapped as an action, wrapping it again with newer settings.",
                category=UserWarning,
            )
            obj = obj.obj
        if obj.__name__.startswith("__"):
            raise ValueError(f"dunder objects cannot become remote : {obj.__name__}")
        action = Action(original)  # type: Action

        action.state = Tuple(
            default=None,
            item_type=(Enum, str),
            allow_None=True,
            accept_list=True,
            accept_item=True,
        ).validate_and_adapt(state)

        if "request" in getfullargspec(obj).kwonlyargs:
            action.request_as_argument = True

        action.create_task = kwargs.get("create_task", False)
        action.safe = kwargs.get("safe", False)
        action.idempotent = kwargs.get("idempotent", False)
        action.synchronous = kwargs.get("synchronous", True)

        if isclassmethod(original):
            action.iscoroutine = has_async_def(obj)
            action.isclassmethod = True
        elif issubklass(obj, ParameterizedFunction):
            action.iscoroutine = iscoroutinefunction(obj.__call__)
            action.isparameterized = True
        else:
            action.iscoroutine = iscoroutinefunction(obj)

        if not input_schema:
            try:
                input_schema = get_input_model_from_signature(obj, remove_first_positional_arg=True)
            except Exception as ex:
                warnings.warn(
                    f"Could not infer input schema for {obj.__name__} due to - {ex!s}. "
                    + "Considering filing a bug report if you think this should have worked correctly",
                    category=RuntimeWarning,
                )
        if input_schema:
            if not SchemaValidators.is_supported(input_schema):
                raise TypeError(
                    "no registered schema validator can validate against the input schema "
                    + f"of {obj.__name__}, which is of type {type(input_schema)}. Supply a JSON schema, "
                    + "a pydantic model, or register a validator that matches it with "
                    + "SchemaValidators.register()."
                )
            if global_config.VALIDATE_SCHEMAS:
                SchemaValidators.check_schema(input_schema)
        action.argument_schema = input_schema

        if not output_schema:
            try:
                output_schema = get_return_type_from_signature(obj)
            except Exception as ex:
                warnings.warn(
                    f"Could not infer output schema for {obj.__name__} due to {ex!s}. "
                    + "Considering filing a bug report if you think this should have worked correctly",
                    category=RuntimeWarning,
                )

        if output_schema:
            # output is not validated by us, so we just check the schema and dont create a validator
            if not SchemaValidators.is_supported(output_schema):
                raise TypeError(
                    "no registered schema validator can validate against the output schema "
                    + f"of {obj.__name__}, which is of type {type(output_schema)}. Supply a JSON schema, "
                    + "a pydantic model, or register a validator that matches it with "
                    + "SchemaValidators.register()."
                )
            if global_config.VALIDATE_SCHEMAS:
                SchemaValidators.check_schema(output_schema)
            action.return_value_schema = output_schema

        return action

    if callable(input_schema):
        raise TypeError(
            "input schema should be a JSON or pydantic BaseModel, not a function/method, "
            + "did you decorate your action wrongly? use @action() instead of @action"
        )
    if any(key not in __action_kw_arguments__ for key in kwargs):
        raise ValueError(
            "Only 'safe', 'idempotent', 'synchronous' are allowed as keyword arguments, "
            + f"unknown arguments found {kwargs.keys()}"
        )
    inner._arguments = dict(  # ty: ignore[unresolved-attribute]
        input_schema=input_schema,
        output_schema=output_schema,
        state=state,
        kwargs=kwargs,
    )
    return inner


__all__ = [action.__name__, Action.__name__]
