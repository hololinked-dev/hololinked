"""Helpers shared by the event loop and its schedulers - a cross-loop event, and thing composition."""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading

from typing import TYPE_CHECKING


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

    is_property_call = lambda node: (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Property"
    )

    body = class_def.body
    i = 0
    while i < len(body):
        stmt = body[i]
        if not isinstance(stmt, ast.Assign):
            i += 1
            continue

        prop_node: ast.Call | None = None
        if is_property_call(stmt.value) and isinstance(stmt.value, ast.Call):
            prop_node = stmt.value
        elif (
            isinstance(stmt.value, (ast.Tuple, ast.List))
            and stmt.value.elts
            and is_property_call(stmt.value.elts[0])
            and isinstance(stmt.value.elts[0], ast.Call)
        ):
            prop_node = stmt.value.elts[0]

        if prop_node is None:
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


__all__ = [
    "CrossLoopEvent",
    "get_all_sub_things_recusively",
    "resolve_property_docstrings",
]
