"""Helpers shared by the core - a cross-loop event, thing composition and action signature checks."""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading
import typing

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from inspect import Parameter, signature
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, create_model

from hololinked.utils import issubklass


if TYPE_CHECKING:
    from hololinked.core.meta import ThingMeta
    from hololinked.core.thing import Thing


class CrossLoopEvent:
    """
    An event that any asyncio loop can await without occupying a thread.

    `threading.Event` as a coroutine safe alternative saturates the running thread pool.
    """

    """
    Claude' report:

    `threading.Event` is the obvious primitive for signalling between the socket listener loop and a
    `Thing`'s own loop, but asyncio can only await one through `run_in_executor(None, event.wait)`,
    which holds a pooled OS thread for the entire duration of the wait. With one wait per idle
    `Thing` and one per in-flight operation, that saturates the listener loop's default
    `ThreadPoolExecutor` (`min(32, cpu_count + 4)` threads) and replies stop being sent.

    This holds nothing while pending: each waiter parks a future on its own loop, and `set()` wakes
    them through `loop.call_soon_threadsafe`. `set()` and `clear()` are safe from any thread, with
    or without a running loop; `wait()` must be called from a coroutine.

    Semantics match `threading.Event` for the set/wait/clear rendezvous the schedulers use,
    including the existing race in which a `set()` landing between a waiter returning and its
    `clear()` is lost. That behaviour is preserved deliberately rather than fixed here.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_set = False
        self._waiters = []  # type: list[tuple[asyncio.AbstractEventLoop, asyncio.Future]]

    def is_set(self) -> bool:
        """
        Whether the event is currently set.

        Returns
        -------
        bool
            `True` if set, `False` otherwise
        """
        return self._is_set

    def set(self) -> None:
        """Set the event and wake every waiter on its own loop."""
        with self._lock:
            if self._is_set:
                return
            self._is_set = True
            waiters, self._waiters = self._waiters, []
        for loop, future in waiters:
            try:
                loop.call_soon_threadsafe(self._resolve, future)
            except RuntimeError:
                pass  # the waiter's loop is already closed, so there is nobody left to wake

    def clear(self) -> None:
        """Unset the event, so that the next `wait()` blocks again."""
        with self._lock:
            self._is_set = False

    async def wait(self) -> None:
        """Wait until the event is set, without occupying a thread while pending."""
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._is_set:
                return
            entry = (loop, loop.create_future())
            self._waiters.append(entry)
        try:
            await entry[1]
        finally:
            # a cancelled waiter must not be left behind for set() to walk over
            with self._lock:
                if entry in self._waiters:
                    self._waiters.remove(entry)

    @staticmethod
    def _resolve(future: asyncio.Future) -> None:
        if not future.done():
            future.set_result(None)


def get_input_model_from_signature(
    func: Callable,
    remove_first_positional_arg: bool = False,
    ignore: Sequence[str] | None = None,
    model_for_empty_annotations: bool = False,
) -> type[BaseModel] | None:
    """
    Create a pydantic model for a function's signature.

    Parameters
    ----------
    func: Callable
        The function for which to create the pydantic model.
    remove_first_positional_arg: bool, optional
        Remove the first argument from the model. This is appropriate for methods,
        as the first argument, self, is baked in when it's called, but is present
        in the signature.
    ignore: Sequence[str], optional
        Ignore arguments that have the specified name.
    model_for_empty_annotations: bool, optional
        If True, create a model even if there are no annotations.

    Raises
    ------
    ValueError
        if the first positional argument is to be removed but the signature has none

    Returns
    -------
    Type[BaseModel] or None
        A pydantic model class describing the input parameters, or None if there are no parameters.
    """
    parameters = OrderedDict(signature(func).parameters)  # type: OrderedDict[str, Parameter]
    if len(parameters) == 0:
        return None

    if all(p.annotation is Parameter.empty for p in parameters.values()) and not model_for_empty_annotations:
        return None

    if remove_first_positional_arg:
        name, parameter = next(iter(parameters.items()))  # get the first parameter
        if parameter.kind in (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD):
            raise ValueError("Can't remove first positional argument: there is none.")
        del parameters[name]

    # fields is a dictionary of tuples of (type, default) that defines the input model
    type_hints = typing.get_type_hints(func, include_extras=True)
    fields = {}  # type: dict[str, tuple[type, Any]]
    for name, p in parameters.items():
        if ignore and name in ignore:
            continue
        if p.kind == Parameter.VAR_KEYWORD:
            keyword_type = dict[str, typing.Any] if p.annotation is Parameter.empty else type_hints[name]
            p_type = typing.Annotated[keyword_type, Parameter.VAR_KEYWORD]
            default = dict() if p.default is Parameter.empty else p.default
        elif p.kind == Parameter.VAR_POSITIONAL:
            positional_type = tuple if p.annotation is Parameter.empty else type_hints[name]
            p_type = typing.Annotated[positional_type, Parameter.VAR_POSITIONAL]
            default = tuple() if p.default is Parameter.empty else p.default
        else:
            # `type_hints` does more processing than p.annotation - but will
            # not have entries for missing annotations.
            p_type = typing.Any if p.annotation is Parameter.empty else type_hints[name]
            # pydantic uses `...` to represent missing defaults (i.e. required params)
            default = Field(...) if p.default is Parameter.empty else p.default
        fields[name] = (p_type, default)

    # If there are no fields, we don't want to return a model
    if len(fields) == 0:
        return None

    model = create_model(  # type: ignore[call-overload]
        f"{func.__name__}_input",  # ty: ignore[unresolved-attribute]  # a function always has one
        **fields,
        __config__=ConfigDict(extra="forbid", strict=True, arbitrary_types_allowed=True),
    )
    return model


class ModelRoot(RootModel):
    """A RootModel accepting arbitrary types, base of the models wrapping plain types."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


def wrap_plain_types_in_rootmodel(model: Any) -> type[BaseModel | RootModel]:
    """
    Ensure a type is a subclass of BaseModel.

    If a `BaseModel` subclass is passed to this function, we will pass it
    through unchanged. Otherwise, we wrap the type in a RootModel.
    In the future, we may explicitly check that the argument is a type
    and not a model instance.

    Returns
    -------
    Type[BaseModel] | Type[RootModel]
        a `BaseModel` subclass which can be used for validation. If the input was already a `BaseModel` subclass,
        it is returned unchanged. Otherwise, a new `RootModel` subclass is returned which wraps the input type.
    """
    if model is None:
        return  # ty: ignore[invalid-return-type]
    if issubklass(model, BaseModel):
        return model
    return create_model(f"{model!r}", root=(model, ...), __base__=ModelRoot)  # type: ignore[call-overload]


def get_return_type_from_signature(func: Callable) -> RootModel | None:
    """
    Determine the return type of a function.

    Returns
    -------
    RootModel | None
        a model for the return annotation, or None when there is none
    """
    sig = inspect.signature(func)
    if sig.return_annotation == inspect.Signature.empty:
        return None  # type: ignore[return-value]
    else:
        # We use `get_type_hints` rather than just `sig.return_annotation`
        # because it resolves forward references, etc.
        type_hints = typing.get_type_hints(func, include_extras=True)

        if (
            "return" not in type_hints
            or type_hints["return"] is typing.Any
            or type_hints["return"] is None
            or type_hints["return"] is type(None)
        ):
            return None

        return wrap_plain_types_in_rootmodel(type_hints["return"])  # ty: ignore[invalid-return-type]  # a RootModel subclass is returned for plain types


def get_all_sub_things_recusively(thing: Thing) -> list[Thing]:
    """
    Get all sub things recursively from a thing.

    Returns
    -------
    list[Thing]
        the thing itself followed by all of its sub things
    """
    sub_things = [thing]
    for sub_thing in thing.sub_things.values():
        sub_things.extend(get_all_sub_things_recusively(sub_thing))
    return sub_things


def resolve_property_docstrings(owner_cls: ThingMeta) -> None:
    r"""Parse owning class source and fill Property.doc from trailing string literals.

    Explicit doc="..." always wins — we skip any property whose doc is already set.

    The function is idempotent: calling it multiple times on the same class
    produces the same result, since it only fills ``doc`` when it is ``None``.
    """
    from hololinked.core.property import Property

    try:
        source = inspect.getsource(owner_cls)
    except (OSError, TypeError, ValueError):
        return

    try:
        tree = ast.parse(source, filename=inspect.getfile(owner_cls))
    except (SyntaxError, IndentationError):
        return

    class_def: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == owner_cls.__name__:
            class_def = node
            break
    if class_def is None:
        return

    body = class_def.body
    i = 0
    while i < len(body):
        stmt = body[i]
        if not isinstance(stmt, ast.Assign):
            i += 1
            continue

        value = stmt.value
        if isinstance(value, (ast.Tuple, ast.List)) and value.elts:
            value = value.elts[0]
        if not isinstance(value, ast.Call):
            i += 1
            continue

        target_names: list[str] = []
        if isinstance(stmt.targets[0], ast.Name):
            target_names.append(stmt.targets[0].id)
        elif isinstance(stmt.targets[0], (ast.Tuple, ast.List)):
            for elt in stmt.targets[0].elts:
                if isinstance(elt, ast.Name):
                    target_names.append(elt.id)

        if not target_names:
            i += 1
            continue

        doc: str | None = None
        next_stmt = body[i + 1] if i + 1 < len(body) else None
        if isinstance(next_stmt, ast.Expr) and isinstance(next_stmt.value, ast.Constant):
            raw = next_stmt.value.value
            if isinstance(raw, str) and raw.strip():
                doc = raw

        for name in target_names:
            if name.startswith("_"):
                continue
            prop = owner_cls.__dict__.get(name)
            if isinstance(prop, Property) and prop.doc is None:
                prop.doc = doc

        i += 1


class SignatureMismatchKind(StrEnum):
    """How the parameters of an action handler do not match the input of the action, worded for the error."""

    SINGLE_VALUE_ARITY = "the input is a single value, so the handler takes exactly one positional parameter"
    POSITIONAL_ONLY = "parameter {name!r} is positional-only, an object input is given by keyword"
    REQUIRED_NOT_IN_INPUT = "required parameter {name!r} is not an input property"
    PROPERTY_NOT_A_PARAMETER = "input property {name!r} is not a parameter"
    ADDITIONAL_NEEDS_KWARGS = "the input allows additional properties, so the handler takes **kwargs"


@dataclass(frozen=True)
class SignatureMismatch:
    """A mismatch between the parameters of an action handler and the input of the action."""

    kind: SignatureMismatchKind
    name: str | None = None
    """the parameter or input property concerned, None if the mismatch is about the handler as a whole"""

    def __str__(self) -> str:
        return self.kind.value.format(name=self.name)


class InputSignatureError(TypeError):
    """The parameters of an action handler do not match the input of the action, lists every mismatch."""

    def __init__(self, handler: Any, mismatches: list[SignatureMismatch]) -> None:
        """
        Initialize the error.

        Parameters
        ----------
        handler: Any
            the action handler
        mismatches: list[SignatureMismatch]
            every mismatch found
        """
        self.mismatches = mismatches
        super().__init__(
            f"{getattr(handler, '__name__', handler)} does not match the input of the action: "
            + "; ".join(map(str, mismatches))
        )


def check_input_signature(func: Callable, schema: dict[str, Any]) -> None:
    """
    Check that the parameters of an action handler match the input DataSchema of the action.

    The first positional parameter (`self`) and a keyword-only `request` parameter are not part of the input.
    A delegate's method belongs to another object, so its signature has no `self` to skip.
    An object input arrives as keyword arguments, any other input as a single value.

    Parameters
    ----------
    func: Callable
        the action handler, or the `ActionDelegate` calling a method of another object
    schema: dict[str, Any]
        the input DataSchema

    Raises
    ------
    InputSignatureError
        listing every mismatch found
    """
    from hololinked.core.actions import ActionDelegate  # core imports this module

    if isinstance(func, ActionDelegate):
        parameters = list(inspect.signature(func.handler).parameters.values())
    else:
        parameters = list(inspect.signature(func).parameters.values())[1:]
    parameters = [
        parameter
        for parameter in parameters
        if not (parameter.kind is Parameter.KEYWORD_ONLY and parameter.name == "request")
    ]
    mismatches: list[SignatureMismatch] = []
    if not (schema.get("type") == "object" or "properties" in schema):
        positional = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD, Parameter.VAR_POSITIONAL)
        if len(parameters) != 1 or parameters[0].kind not in positional:
            mismatches.append(SignatureMismatch(SignatureMismatchKind.SINGLE_VALUE_ARITY))
    else:
        properties = schema.get("properties", {})
        takes_kwargs = any(parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters)
        keywords = {
            parameter.name
            for parameter in parameters
            if parameter.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
        }
        mismatches += [
            SignatureMismatch(SignatureMismatchKind.POSITIONAL_ONLY, parameter.name)
            for parameter in parameters
            if parameter.kind is Parameter.POSITIONAL_ONLY
        ]
        mismatches += [
            SignatureMismatch(SignatureMismatchKind.REQUIRED_NOT_IN_INPUT, parameter.name)
            for parameter in parameters
            if parameter.name in keywords and parameter.default is Parameter.empty and parameter.name not in properties
        ]
        if not takes_kwargs:
            mismatches += [
                SignatureMismatch(SignatureMismatchKind.PROPERTY_NOT_A_PARAMETER, name)
                for name in sorted(set(properties) | set(schema.get("required", [])))
                if name not in keywords
            ]
        additional = schema.get("additionalProperties", None)
        if additional is not None and additional is not False and not takes_kwargs:
            mismatches.append(SignatureMismatch(SignatureMismatchKind.ADDITIONAL_NEEDS_KWARGS))
    if mismatches:
        raise InputSignatureError(func, mismatches)


def is_unbound_action_delegate(call: Callable, input_schema: dict[str, Any] | None) -> bool:
    """
    Whether a custom action implementation is unbound, i.e. called with the implementation object as first argument.

    Decided from the first parameter only, a keyword-only `request` parameter is not considered.

    Parameters
    ----------
    call: Callable
        the callable invoked for the action, usually the `__call__` of the custom implementation
    input_schema: dict[str, Any] | None
        the input DataSchema of the action, `None` if it has no input

    Returns
    -------
    bool
        True if the implementation object is passed as the first argument, False if called with the input only
    """
    try:
        parameters = [
            parameter
            for parameter in inspect.signature(call).parameters.values()
            if not (parameter.kind is Parameter.KEYWORD_ONLY and parameter.name == "request")
        ]
    except (TypeError, ValueError):
        return True
    positional = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    if not parameters or parameters[0].kind not in positional:
        return False
    first = parameters[0]
    if not input_schema:
        return first.default is Parameter.empty
    if input_schema.get("type") == "object" or "properties" in input_schema:
        return first.name not in input_schema.get("properties", {})
    # a single value input: one positional parameter takes the value, a second one means the first takes the impl
    return sum(parameter.kind in positional for parameter in parameters) >= 2


def is_unbound_property_delegate(delegate: Any) -> bool:
    """
    Whether a custom property implementation is unbound, i.e. called with the implementation object as first argument.

    Applies to its `get`, `set` and `delete`, decided from the first parameter of `get` only.

    Parameters
    ----------
    delegate: Any
        the custom implementation of the property

    Returns
    -------
    bool
        True if the implementation object is passed as the first argument, False if called with the value only
    """
    get = getattr(delegate, "get", None)
    if get is None:
        return True
    try:
        parameters = list(inspect.signature(get).parameters.values())
    except (TypeError, ValueError):
        return True
    if not parameters:
        return False
    first = parameters[0]
    if first.kind is Parameter.VAR_POSITIONAL:
        return True
    positional = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    return first.kind in positional and first.default is Parameter.empty


__all__ = [
    "CrossLoopEvent",
    "get_input_model_from_signature",
    "ModelRoot",
    "wrap_plain_types_in_rootmodel",
    "get_return_type_from_signature",
    "get_all_sub_things_recusively",
    "resolve_property_docstrings",
    "SignatureMismatchKind",
    "SignatureMismatch",
    "InputSignatureError",
    "check_input_signature",
    "is_unbound_action_delegate",
    "is_unbound_property_delegate",
]
