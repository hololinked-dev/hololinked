"""Metadata formats, or device description languages, a `Thing` can be described in."""

from typing import TYPE_CHECKING

from hololinked.utils import lazy_module_getattr


__all__ = ["WoTMetadata"]

_lazy: dict[str, str] = {
    "WoTMetadata": ".td",
}
"""Name of a metadata format mapped to the module it is imported from, resolved lazily."""

__getattr__ = lazy_module_getattr(__name__, _lazy, globals())


if TYPE_CHECKING:
    from .td import WoTMetadata as WoTMetadata
