"""
Concrete implementations of serializers.

adopted from pyro - https://github.com/irmen/Pyro5 - see following license

MIT License

Copyright (c) Irmen de Jong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from typing import TYPE_CHECKING


__all__ = [
    "JSONSerializer",
    "MsgpackSerializer",
    "PickleSerializer",
    "PythonBuiltinJSONSerializer",
    "SerpentSerializer",
    "TextSerializer",
]

_lazy: dict[str, tuple[str, str]] = {
    "JSONSerializer": (".json", "JSONSerializer"),
    "PythonBuiltinJSONSerializer": (".json", "PythonBuiltinJSONSerializer"),
    "MsgpackSerializer": (".msgpack", "MsgpackSerializer"),
    "PickleSerializer": (".pickle", "PickleSerializer"),
    "TextSerializer": (".text", "TextSerializer"),
    "SerpentSerializer": (".serpent", "SerpentSerializer"),
}


def __getattr__(name: str):
    if name not in _lazy:  # only lazy stuff for this adapter for now
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    module_path, attr = _lazy[name]
    mod = importlib.import_module(module_path, package=__name__)
    val = getattr(mod, attr)
    globals()[name] = val  # cache so subsequent access skips __getattr__
    return val


if TYPE_CHECKING:
    from .json import JSONSerializer as JSONSerializer
    from .json import PythonBuiltinJSONSerializer as PythonBuiltinJSONSerializer
    from .msgpack import MsgpackSerializer as MsgpackSerializer
    from .pickle import PickleSerializer as PickleSerializer
    from .serpent import SerpentSerializer as SerpentSerializer
    from .text import TextSerializer as TextSerializer
