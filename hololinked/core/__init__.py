"""
Core logic, what is a Property, Action or Event, what is a Thing and how request-reply and pub-sub patterns work.

State machines, meta classes, descriptor registries and the concrete implementation of how an operation is executed
is also included here.
"""

from typing import TYPE_CHECKING

# Interfaces must be available to register adappters
from .interfaces import BaseConfigurationRepository as BaseConfigurationRepository
from .interfaces import BaseSchemaValidator as BaseSchemaValidator
from .interfaces import BaseSerializer as BaseSerializer


__all__ = [
    "BaseSchemaValidator",
    "BaseSerializer",
    "BaseConfigurationRepository",
    "action",
    "Action",
    "Event",
    "ThingMeta",
    "Property",
    "StateMachine",
    "Thing",
]

# Submodules that use SchemaValidatorClasses / Serializers are loaded lazily so
# that hololinked/__init__.py can finish registering the adapters (schema_validators,
# serializers) before any class body in meta.py / actions.py / property.py executes.
_lazy: dict[str, tuple[str, str]] = {
    "action": (".actions", "action"),
    "Action": (".actions", "Action"),
    "Event": (".events", "Event"),
    "ThingMeta": (".meta", "ThingMeta"),
    "Property": (".property", "Property"),
    "StateMachine": (".state_machine", "StateMachine"),
    "Thing": (".thing", "Thing"),
}


def __getattr__(name: str):
    if name in _lazy:
        import importlib

        module_path, attr = _lazy[name]
        mod = importlib.import_module(module_path, package=__name__)
        val = getattr(mod, attr)
        globals()[name] = val  # cache so subsequent access skips __getattr__
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from .actions import Action as Action
    from .actions import action as action
    from .events import Event as Event
    from .meta import ThingMeta as ThingMeta
    from .property import Property as Property
    from .state_machine import StateMachine as StateMachine
    from .thing import Thing as Thing
