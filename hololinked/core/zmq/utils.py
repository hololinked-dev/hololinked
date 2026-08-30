"""Concurrency primitives shared by the RPC server and its schedulers."""

from __future__ import annotations

import asyncio
import threading


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


__all__ = [CrossLoopEvent.__name__]
