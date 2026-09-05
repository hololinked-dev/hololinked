"""
Core logic, what is a Property, Action or Event, what is a Thing and how request-reply and pub-sub patterns work.

State machines, meta classes, descriptor registries and the concrete implementation of how an operation is executed
is also included here.
"""

from typing import TYPE_CHECKING

# Interfaces must be available to register adappters
from hololinked.core.interfaces import BaseConfigurationRepository as BaseConfigurationRepository
from hololinked.core.interfaces import BaseSchemaValidator as BaseSchemaValidator
from hololinked.core.interfaces import BaseSerializer as BaseSerializer


__all__ = [
    "Action",
    "BaseConfigurationRepository",
    "BaseSchemaValidator",
    "BaseSerializer",
    "Event",
    "Property",
    "StateMachine",
    "Thing",
    "ThingMeta",
    "action",
]

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
    from hololinked.core.actions import Action as Action
    from hololinked.core.actions import action as action
    from hololinked.core.events import Event as Event
    from hololinked.core.meta import ThingMeta as ThingMeta
    from hololinked.core.property import Property as Property
    from hololinked.core.state_machine import StateMachine as StateMachine
    from hololinked.core.thing import Thing as Thing
