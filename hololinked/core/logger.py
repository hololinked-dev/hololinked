import asyncio
import datetime
import logging
import threading
import time

from collections import deque
from typing import Any  # noqa: F401

import structlog

from .actions import action as remote_method
from .events import Event
from .properties import Integer, List, Number
from .thing import Thing as RemoteObject


log_message_schema = {
    "type": "object",
    "properties": {
        "level": {
            "type": "string",
            "description": "log level, one of DEBUG, INFO, WARN, ERROR, CRITICAL",
        },
        "timestamp": {
            "type": "string",
            "description": "timestamp of the log entry",
        },
        "thread_id": {
            "type": "integer",
            "description": "ID of the thread that generated the log entry",
        },
        "message": {
            "type": "string",
            "description": "log message",
        },
    },
    "required": ["level", "timestamp", "thread_id", "message"],
    "additionalProperties": False,
}


class RemoteAccessHandler(logging.Handler, RemoteObject):
    """
    Log handler with remote access attached to `Thing`'s logger, capable of streaming the log entries as events.
    Set `remote_accessible_logger` to True in the `Thing` to enable this handler.
    The schema of the pushed logs is an array of objects, where each object is:

    ```json
    {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "description": "log level, one of DEBUG, INFO, WARN, ERROR, CRITICAL"
            },
            "timestamp": {
                "type": "string",
                "description": "timestamp of the log entry"
            },
            "thread_id": {
                "type": "integer",
                "description": "ID of the thread that generated the log entry"
            },
            "message": {
                "type": "string",
                "description": "log message"
            }
        },
        "required": ["level", "timestamp", "thread_id", "message"],
        "additionalProperties": false
    }
    ```
    """

    def __init__(self, id: str = "logger", maxlen: int = 500, stream_interval: float = 1.0, **kwargs) -> None:
        """
        Parameters
        ----------
        id: str, default 'logger'
            id of the object, generally only one instance per `Thing` necessary, therefore defaults to
            'logger'
        maxlen: int, default 500
            history of log entries to store in RAM
        stream_interval: float, default 1.0
            when streaming logs using log-events endpoint, this value is the stream interval.
        **kwargs:
            additional keyword arguments, currently supports:

            - `len_debug`: int
                length of debug logs, default maxlen/5
            - `len_info`: int
                length of info logs, default maxlen/5
            - `len_warn`: int
                length of warn logs, default maxlen/5
            - `len_error`: int
                length of error logs, default maxlen/5
            - `len_critical`: int
                length of critical logs, default maxlen/5
        """
        RemoteObject.__init__(self, id=id, **kwargs)
        logging.Handler.__init__(self)
        self.set_maxlen(maxlen, **kwargs)
        self.stream_interval = stream_interval
        self.diff_logs = []
        self._push_events = False
        self._events_thread = None

    log_events = Event(doc="stream logs", schema=log_message_schema)

    stream_interval = Number(
        default=1.0,
        bounds=(0.025, 60.0),
        crop_to_bounds=True,
        step=0.05,
        doc="interval at which logs should be published to a client.",
    )  # type: float

    def get_maxlen(self):
        return self._maxlen

    def set_maxlen(self, value: int, **kwargs) -> None:
        self._maxlen = value
        self._debug_logs = deque(maxlen=kwargs.pop("len_debug", int(value / 5)))
        self._info_logs = deque(maxlen=kwargs.pop("len_info", int(value / 5)))
        self._warn_logs = deque(maxlen=kwargs.pop("len_warn", int(value / 5)))
        self._error_logs = deque(maxlen=kwargs.pop("len_error", int(value / 5)))
        self._critical_logs = deque(maxlen=kwargs.pop("len_critical", int(value / 5)))
        self._execution_logs = deque(maxlen=value)

    maxlen = Integer(
        default=100,
        bounds=(1, None),
        crop_to_bounds=True,
        fget=get_maxlen,
        fset=set_maxlen,
        doc="length of execution log history to store",
    )  # type: int

    @remote_method(
        input_schema={
            "scheduling": {"type": "string", "enum": ["threaded", "async"]},
            "stream_interval": {"type": "number", "minimum": 0.025},
        },
    )
    def push_events(self, scheduling: str = "threaded", stream_interval: float = 1) -> None:
        """
        Push log events to a client.

        Parameters
        ----------
        scheduling: str
            'threaded' or 'async'. threaded starts a new thread, async schedules a task to the
            main event loop.
        stream_interval: float
            push interval in seconds.
        """
        self.stream_interval = stream_interval
        if scheduling == "async":
            asyncio.get_event_loop().call_soon(lambda: asyncio.create_task(self._async_push_diff_logs()))
        elif scheduling == "threading":
            if self._events_thread is not None:  # dont create again if one is already running
                self._events_thread = threading.Thread(target=self._push_diff_logs)
                self._events_thread.start()
        else:
            raise ValueError(f"scheduling can only be 'threaded' or 'async'. Given value {scheduling}")

    @remote_method()
    def stop_events(self) -> None:
        """stop pushing log events"""
        self._push_events = False
        if self._events_thread:  # coroutine variant will resolve automatically
            self._events_thread.join()
            self._owner.logger.debug(f"joined log event source with thread-id {self._events_thread.ident}.")
            self._events_thread = None

    def emit(self, record: logging.LogRecord) -> None:
        # automatically called when a log entry is created
        # log_entry = self.format(record)
        self.format(record)
        info = {
            "level": record.levelname,
            "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "thread_id": threading.get_ident(),
            "message": record.msg,
        }
        if record.levelno < logging.INFO:
            self._debug_logs.appendleft(info)
        elif record.levelno >= logging.INFO and record.levelno < logging.WARN:
            self._info_logs.appendleft(info)
        elif record.levelno >= logging.WARN and record.levelno < logging.ERROR:
            self._warn_logs.appendleft(info)
        elif record.levelno >= logging.ERROR and record.levelno < logging.CRITICAL:
            self._error_logs.appendleft(info)
        elif record.levelno >= logging.CRITICAL:
            self._critical_logs.appendleft(info)
        self._execution_logs.appendleft(info)

        if self._push_events:
            self.diff_logs.insert(0, info)

    def _push_diff_logs(self) -> None:
        self._push_events = True
        while self._push_events:
            time.sleep(self.stream_interval)
            if len(self.diff_logs) > 0:
                self.log_events.push(self.diff_logs)
                self.diff_logs.clear()
        # give time to collect final logs with certainty
        # self.owner.logger.info(f"ending log event source with thread-id {threading.get_ident()}.")

    async def _async_push_diff_logs(self) -> None:
        while self._push_events:
            await asyncio.sleep(self.stream_interval)
            # TODO: can use an async EventPublisher in the future
            if len(self.diff_logs) > 0:
                self.log_events.push(self.diff_logs)
                self.diff_logs.clear()
        # self.owner.logger.info("ending log events.")

    debug_logs = List(default=[], readonly=True, fget=lambda self: self._debug_logs, doc="logs at logging.DEBUG level")  # type: list[dict[str, Any]]

    warn_logs = List(default=[], readonly=True, fget=lambda self: self._warn_logs, doc="logs at logging.WARN level")  # type: list[dict[str, Any]]

    info_logs = List(default=[], readonly=True, fget=lambda self: self._info_logs, doc="logs at logging.INFO level")  # type: list[dict[str, Any]]

    error_logs = List(default=[], readonly=True, fget=lambda self: self._error_logs, doc="logs at logging.ERROR level")  # type: list[dict[str, Any]]

    critical_logs = List(
        default=[], readonly=True, fget=lambda self: self._critical_logs, doc="logs at logging.CRITICAL level"
    )  # type: list[dict[str, Any]]

    execution_logs = List(
        default=[],
        readonly=True,
        fget=lambda self: self._execution_logs,
        doc="logs at all levels accumulated in order of collection/execution",
    )  # type: list[dict[str, Any]]


def prepare_object_logger(instance: RemoteObject, remote_access: bool = False) -> None:
    """
    Setup logger for the object with default settings. If a logger is already present, it is not recreated.
    If remote access is present, it is not recreated. This is a single-shot method to be run at __init__.

    Parameters
    ----------
    instance: Thing
        the Thing instance for which logger is to be prepared
    remote_access: bool
        if True, a RemoteAccessHandler is attached to the logger.
    """
    if instance.logger is None:
        instance.logger = structlog.get_logger().bind(
            component="thing",
            Thing=instance.__class__.__name__,
            thing_id=instance.id,
        )

    if isinstance(instance.logger, structlog.stdlib.BoundLoggerBase):
        stdlib_logger = instance.logger._logger
    else:
        stdlib_logger = instance.logger
    if not isinstance(stdlib_logger, logging.Logger):
        if remote_access:
            instance.logger.warning(
                "logger is not an instance of logging.Logger, cannot setup a RemoteAccessHandler "
                + "although it has been requested"
            )
        return

    if remote_access and not any(isinstance(handler, RemoteAccessHandler) for handler in stdlib_logger.handlers):
        instance._remote_access_loghandler = RemoteAccessHandler(
            id="logger", maxlen=500, emit_interval=1, logger=stdlib_logger
        )
        # we set logger=instance.logger because so that we dont recreate one for remote access handler
        stdlib_logger.addHandler(instance._remote_access_loghandler)

    if not isinstance(instance, RemoteAccessHandler):
        for handler in stdlib_logger.handlers:
            # if remote access is True or not, if such a handler is found, make it a sub thing
            if isinstance(handler, RemoteAccessHandler):
                instance._remote_access_loghandler = handler


class LogHistoryHandler(logging.Handler):
    """
    Log history handler. Add and remove this handler at specific points to hold specific logs that are generated
    between those points. Currently used by execution context within `RPCServer` where one can fetch the
    execution logs that were collected during a specific operation.
    """

    def __init__(self, log_list: list | None = None):
        """
        Parameters
        ----------
        log_list: list, optional
            Initial set of log entries to start with. Optional, defaults to empty list.
        """
        super().__init__()
        self.log_list: list[dict] = [] if not log_list else log_list

    def emit(self, record: logging.LogRecord):
        # log_entry = self.format(record)
        self.format(record)
        self.log_list.insert(
            0,
            {
                "level": record.levelname,
                "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.%f"),
                "thread_id": threading.get_ident(),
                "message": record.msg,
            },
        )


__all__ = [LogHistoryHandler.__name__, RemoteAccessHandler.__name__]
