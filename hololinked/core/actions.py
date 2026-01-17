import warnings

from enum import Enum
from inspect import getfullargspec, iscoroutinefunction
from types import FunctionType, MethodType
from typing import Any

import jsonschema

from pydantic import BaseModel, RootModel

from ..constants import JSON
from ..param.parameterized import ParameterizedFunction
from ..schema_validators.validators import JSONSchemaValidator, PydanticSchemaValidator
from ..utils import (
    get_input_model_from_signature,
    get_return_type_from_signature,
    has_async_def,
    isclassmethod,
    issubklass,
)
from .dataklasses import ActionInfoValidator
from .exceptions import StateMachineError


class Action:
    """
    Object that models an action.
    These actions are unbound and return a bound action when accessed using the owning object.
    """

    __slots__ = ["obj", "owner", "_execution_info"]

    def __init__(self, obj: MethodType) -> None:
        """
        Parameters
        ----------
        obj: MethodType
            the method that is being wrapped as an action
        """
        self.obj = obj

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
        if instance is None and not self._execution_info.isclassmethod:
            return self
        if self._execution_info.iscoroutine:
            return BoundAsyncAction(self.obj, self, instance, owner)
        return BoundSyncAction(self.obj, self, instance, owner)

    def __call__(self, *args, **kwargs):
        raise NotImplementedError(
            f"Cannot invoke unbound action {self.name} of {self.owner.__name__}."
            + " Bound methods must be called, not the action itself. Use the appropriate instance to call the method."
        )

    @property
    def name(self) -> str:
        """name of the action"""
        return self.obj.__name__

    @property
    def execution_info(self) -> ActionInfoValidator:
        """
        internal dataclass that holds all information about the action

        TODO: this can be refactored
        """
        return self._execution_info

    @execution_info.setter
    def execution_info(self, value: ActionInfoValidator) -> None:
        if not isinstance(value, ActionInfoValidator):
            raise TypeError("execution_info must be of type ActionInfoValidator")
        self._execution_info = value  # type: ActionInfoValidator

    def to_affordance(self, owner_inst=None):
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
        from ..td import ActionAffordance

        return ActionAffordance.generate(self, owner_inst or self.owner)


class BoundAction:
    """
    A bound action - base class for both sync and async methods.
    """

    __slots__ = [
        "obj",
        "execution_info",
        "descriptor",
        "owner_inst",
        "owner",
        "bound_obj",
    ]

    def __init__(self, obj: FunctionType, descriptor: Action, owner_inst, owner) -> None:
        self.obj = obj
        self.descriptor = descriptor
        self.execution_info = descriptor._execution_info
        self.owner = owner
        self.owner_inst = owner_inst
        self.bound_obj = owner if self.execution_info.isclassmethod else owner_inst

    def __post_init__(self):
        # never called, neither possible to call, only type hinting
        from .thing import Thing, ThingMeta

        # owner class and instance
        self.owner: ThingMeta
        self.owner_inst: Thing
        self.obj: FunctionType
        # the validator that was used to accept user inputs to this action.
        # stored only for reference, hardly used.
        self._execution_info: ActionInfoValidator

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
        """
        if self.execution_info.isparameterized and len(args) > 0:
            raise RuntimeError("parameterized functions cannot have positional arguments")
        if self.owner_inst is None:
            return
        if self.execution_info.state is None or (
            hasattr(self.owner_inst, "state_machine")
            and self.owner_inst.state_machine.current_state in self.execution_info.state
        ):
            if self.execution_info.schema_validator is not None:
                self.execution_info.schema_validator.validate_method_call(args, kwargs)
        else:
            raise StateMachineError(
                "Thing '{}' is in '{}' state, however action can be executed only in '{}' state".format(
                    self.owner_inst,
                    self.owner_inst.state,
                    self.execution_info.state,
                )
            )

    @property
    def name(self) -> str:
        """name of the action"""
        return self.obj.__name__

    def __call__(self, *args, **kwargs):
        raise NotImplementedError("call must be implemented by subclass")

    def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
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

    def to_affordance(self):
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
        return Action.to_affordance(self.descriptor, self.owner_inst or self.owner)


class BoundSyncAction(BoundAction):
    """
    non async(io) action call. The call is passed to the method as-it-is to allow local
    invocation without state machine checks. Use `external_call` to have validation.
    """

    def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        self.validate_call(args, kwargs)
        return self.__call__(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        if self.execution_info.isclassmethod:
            return self.obj(*args, **kwargs)
        return self.obj(self.bound_obj, *args, **kwargs)


class BoundAsyncAction(BoundAction):
    """
    async(io) action call. The call is passed to the method as-it-is to allow local
    invocation without state machine checks. Use `external_call` to have validation.
    """

    async def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        self.validate_call(args, kwargs)
        return await self.__call__(*args, **kwargs)

    async def __call__(self, *args, **kwargs):
        if self.execution_info.isclassmethod:
            return await self.obj(*args, **kwargs)
        return await self.obj(self.bound_obj, *args, **kwargs)


__action_kw_arguments__ = ["safe", "idempotent", "synchronous"]


def action(
    input_schema: JSON | BaseModel | RootModel | None = None,
    output_schema: JSON | BaseModel | RootModel | None = None,
    state: str | Enum | None = None,
    **kwargs,
) -> Action:
    """
    Decorate on your methods to make them accessible remotely or create 'actions' out of them. When used with hardware,
    actions generally command the hardware to do something.

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
    """

    def inner(obj):
        input_schema = inner._arguments.get("input_schema", None)
        output_schema = inner._arguments.get("output_schema", None)
        state = inner._arguments.get("state", None)
        kwargs = inner._arguments.get("kwargs", {})

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
            if obj.execution_info.isclassmethod:
                raise RuntimeError("cannot wrap a classmethod as action once again, please skip")
            warnings.warn(
                f"{obj.name} is already wrapped as an action, wrapping it again with newer settings.",
                category=UserWarning,
            )
            obj = obj.obj
        if obj.__name__.startswith("__"):
            raise ValueError(f"dunder objects cannot become remote : {obj.__name__}")
        execution_info_validator = ActionInfoValidator()
        if state is not None:
            if isinstance(state, (Enum, str)):
                execution_info_validator.state = (state,)
            else:
                execution_info_validator.state = state
        if "request" in getfullargspec(obj).kwonlyargs:
            execution_info_validator.request_as_argument = True
        execution_info_validator.isaction = True
        execution_info_validator.obj = original
        execution_info_validator.create_task = kwargs.get("create_task", False)
        execution_info_validator.safe = kwargs.get("safe", False)
        execution_info_validator.idempotent = kwargs.get("idempotent", False)
        execution_info_validator.synchronous = kwargs.get("synchronous", True)

        if isclassmethod(original):
            execution_info_validator.iscoroutine = has_async_def(obj)
            execution_info_validator.isclassmethod = True
        elif issubklass(obj, ParameterizedFunction):
            execution_info_validator.iscoroutine = iscoroutinefunction(obj.__call__)
            execution_info_validator.isparameterized = True
        else:
            execution_info_validator.iscoroutine = iscoroutinefunction(obj)

        if not input_schema:
            try:
                input_schema = get_input_model_from_signature(obj, remove_first_positional_arg=True)
            except Exception as ex:
                warnings.warn(
                    f"Could not infer input schema for {obj.__name__} due to - {str(ex)}. "
                    + "Considering filing a bug report if you think this should have worked correctly",
                    category=RuntimeWarning,
                )
        if input_schema:
            if isinstance(input_schema, dict):
                execution_info_validator.schema_validator = JSONSchemaValidator(input_schema)
            elif issubklass(input_schema, (BaseModel, RootModel)):
                execution_info_validator.schema_validator = PydanticSchemaValidator(input_schema)
            else:
                raise TypeError(
                    "input schema must be a JSON schema or a Pydantic model, got {}".format(type(input_schema))
                )
        execution_info_validator.argument_schema = input_schema

        if not output_schema:
            try:
                output_schema = get_return_type_from_signature(obj)
            except Exception as ex:
                warnings.warn(
                    f"Could not infer output schema for {obj.__name__} due to {str(ex)}. "
                    + "Considering filing a bug report if you think this should have worked correctly",
                    category=RuntimeWarning,
                )

        if output_schema:
            # output is not validated by us, so we just check the schema and dont create a validator
            if isinstance(output_schema, dict):
                jsonschema.Draft7Validator.check_schema(output_schema)
                execution_info_validator.return_value_schema = output_schema
            elif issubklass(output_schema, (BaseModel, RootModel)):
                execution_info_validator.return_value_schema = output_schema
            else:
                raise TypeError(
                    "output schema must be a JSON schema or a Pydantic model, got {}".format(type(output_schema))
                )

        final_obj = Action(original)  # type: Action
        final_obj.execution_info = execution_info_validator
        return final_obj

    if callable(input_schema):
        raise TypeError(
            "input schema should be a JSON or pydantic BaseModel, not a function/method, "
            + "did you decorate your action wrongly? use @action() instead of @action"
        )
    if any(key not in __action_kw_arguments__ for key in kwargs.keys()):
        raise ValueError(
            "Only 'safe', 'idempotent', 'synchronous' are allowed as keyword arguments, "
            + f"unknown arguments found {kwargs.keys()}"
        )
    inner._arguments = dict(
        input_schema=input_schema,
        output_schema=output_schema,
        state=state,
        kwargs=kwargs,
    )
    return inner


__all__ = [action.__name__, Action.__name__]
