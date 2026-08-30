"""
Storage backends for `Thing` instances.

When properties are written, their values can be dispatched to store them in different storage backends.
Whenever the `Thing` instance is reinitialized, these stored values can be reloaded.
This helps to backup running configuration and survive those values in case of power-cycles or crashes.
"""

from typing import TYPE_CHECKING

from hololinked.utils import lazy_module_getattr


__all__ = [
    "JSONFileStorage",
    "MongoDB",
    "SQLAlchemyDB",
]

_lazy: dict[str, str] = {
    "JSONFileStorage": ".jsonfile",
    "MongoDB": ".mongodb",
    "SQLAlchemyDB": ".sqlalchemydb",
}
"""Name of a storage backend mapped to the module it is imported from, resolved lazily."""

__getattr__ = lazy_module_getattr(__name__, _lazy, globals())


if TYPE_CHECKING:
    from .jsonfile import JSONFileStorage as JSONFileStorage
    from .mongodb import MongoDB as MongoDB
    from .sqlalchemydb import SQLAlchemyDB as SQLAlchemyDB
