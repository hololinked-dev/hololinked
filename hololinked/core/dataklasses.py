"""
The following is a list of all dataclasses used to store information on the exposed
resources on the network. These classese are generally not for consumption by the package-end-user.
"""

from enum import Enum
from types import FunctionType, MethodType
from typing import Any

from pydantic import BaseModel, RootModel

from ..constants import USE_OBJECT_NAME
from ..param.parameterized import ParameterizedMetaclass
from ..param.parameters import Boolean, ClassSelector, Parameter, String, Tuple
from ..schema_validators import BaseSchemaValidator
from ..utils import issubklass


# TODO, this class will be removed in future and merged directly into the corresponding object
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
    isaction : bool, default False
        True for a method or function or callable
    isproperty : bool, default False
        True for a property
    """

    state = Tuple(
        default=None,
        item_type=(Enum, str),
        allow_None=True,
        accept_list=True,
        accept_item=True,
        doc="State machine state at which a callable will be executed or attribute/property can be written.",
    )  # type: tuple[Enum | str]

    obj = ClassSelector(
        default=None,
        allow_None=True,
        class_=(
            FunctionType,
            MethodType,
            classmethod,
            Parameter,
            ParameterizedMetaclass,
        ),  # Property will need circular import so we stick to base class Parameter
        doc="the unbound object like the unbound method",
    )

    obj_name = String(
        default=USE_OBJECT_NAME,
        doc="the name of the object which will be supplied to the ``ObjectProxy`` class to populate its own namespace.",
    )  # type: str

    isaction = Boolean(default=False, doc="True for a method or function or callable")  # type: bool

    isproperty = Boolean(default=False, doc="True for a property")  # type: bool

    def __init__(self, **kwargs) -> None:
        # No full-scale checks for unknown keyword arguments as the class
        # is used by the developer, so please try to be error-proof
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

    request_as_argument = Boolean(
        default=False,
        doc="if True, http/RPC request object will be passed as an argument to the callable.",
    )  # type: bool

    argument_schema = Parameter(
        default=None,
        allow_None=True,
        # due to schema validation, this has to be a dict, and not a special dict like TypedDict
        doc="JSON schema validations for arguments of a callable",
    )

    return_value_schema = Parameter(
        default=None,
        allow_None=True,
        # due to schema validation, this has to be a dict, and not a special dict like TypedDict
        doc="schema for return value of a callable",
    )

    create_task = Boolean(default=True, doc="should a coroutine be tasked or run in the same loop?")  # type: bool

    iscoroutine = Boolean(
        default=False,  # not sure if isFuture or isCoroutine is correct, something to fix later
        doc="whether the callable should be awaited",
    )  # type: bool

    safe = Boolean(default=True, doc="metadata information whether the action is safe to execute")  # type: bool

    idempotent = Boolean(default=False, doc="metadata information whether the action is idempotent")  # type: bool

    synchronous = Boolean(default=True, doc="metadata information whether the action is synchronous")  # type: bool

    isparameterized = Boolean(default=False, doc="True for a parameterized function")  # type: bool

    isclassmethod = Boolean(default=False, doc="True for a classmethod")  # type: bool

    schema_validator = ClassSelector(
        default=None,
        allow_None=True,
        class_=BaseSchemaValidator,
        doc="schema validator for the callable if to be validated server side",
    )  # type: BaseSchemaValidator

    @argument_schema.getter
    def _get_argument_schema(self):
        return getattr(self, "_argument_schema", None)

    @argument_schema.setter
    def _set_argument_schema(self, value):
        value = self.action_payload_schema_validator(value)
        setattr(self, "_argument_schema", value)

    @return_value_schema.getter
    def _get_return_value_schema(self):
        return getattr(self, "_return_value_schema", None)

    @return_value_schema.setter
    def _set_return_value_schema(self, value):
        value = self.action_payload_schema_validator(value)
        setattr(self, "_return_value_schema", value)

    def action_payload_schema_validator(self, value: Any) -> Any:
        if value is None or isinstance(value, dict) or issubklass(value, (BaseModel, RootModel)):
            return value
        raise TypeError("Schema must be None, a dict, or a subclass of BaseModel or RootModel")
