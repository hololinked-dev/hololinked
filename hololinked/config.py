"""
adapted from pyro - https://github.com/irmen/Pyro5 - see following license

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

import json
import logging
import os
import tracemalloc
import warnings

from typing import Any  # noqa: F401

import zmq.asyncio

from .utils import set_global_event_loop_policy


class Configuration:
    """
    Allows to auto apply common settings used throughout the package,
    instead of passing these settings as arguments. Import `global_config` variable
    instead of instantitation this class.

    Supports loading configuration from a JSON file whose path is specified
    under environment variable HOLOLINKED_CONFIG.

    Values are usually mutable in runtime, except logging setup and ZMQ context (which refreshes the global state)
    and not type checked. Keys of JSON file must correspond to supported value name. Supported values are -

    `TEMP_DIR` - system temporary directory to store temporary files like IPC sockets.
    default - tempfile.gettempdir().

    `TCP_SOCKET_SEARCH_START_PORT` - starting port number for automatic port searching
    for TCP socket binding, used for event addresses. default 60000.

    `TCP_SOCKET_SEARCH_END_PORT` - ending port number for automatic port searching
    for TCP socket binding, used for event addresses. default 65535.

    `DB_CONFIG_FILE` - file path for database configuration. default None.

    `USE_UVLOOP` - signicantly faster event loop for Linux systems. Reads data from network faster. default False.

    `TRACE_MALLOC` - whether to trace memory allocations using tracemalloc module. default False.

    `VALIDATE_SCHEMAS` - whether to validate JSON schema supplied for properties, actions and events
    (not validation of payload, but validation of schema itself). default True.

    `DEBUG` - whether to print debug logs. default False.

    `LOG_LEVEL` - logging level to use. default logging.INFO, logging.DEBUG if DEBUG is True.

    `COLORED_LOGS` - whether to use colored logs in console. default False.

    `ALLOW_PICKLE` - whether to allow pickle serialization/deserialization. default False.

    `ALLOW_UNKNOWN_SERIALIZATION` - whether to allow unknown serialization formats, specifically from clients. default False.

    Parameters
    ----------
    use_environment: bool
        load files from JSON file specified under environment
    """

    __slots__ = [
        # folders
        "TEMP_DIR",
        # TCP sockets
        "TCP_SOCKET_SEARCH_START_PORT",
        "TCP_SOCKET_SEARCH_END_PORT",
        # HTTP server
        "ALLOW_CORS",
        # database
        "DB_CONFIG_FILE",
        # Eventloop
        "USE_UVLOOP",
        "TRACE_MALLOC",
        # schema validation
        "VALIDATE_SCHEMAS",
        # ZMQ
        "ZMQ_CONTEXT",
        # make debugging easier
        "DEBUG",
        # logging
        "LOG_LEVEL",
        # "USE_STRUCTLOG",
        "COLORED_LOGS",
        # serializers
        "ALLOW_PICKLE",
        "ALLOW_UNKNOWN_SERIALIZATION",
    ]

    def __init__(self, use_environment: bool = False):
        self.load_variables(use_environment)
        self.setup()

    def load_variables(self, use_environment: bool = False):
        """
        set default values & use the values from environment file.
        Set use_environment to False to not use environment file.
        """
        # note that all variables have not been implemented yet,
        # things just come and go as of now
        self.TEMP_DIR = os.path.join(os.path.expanduser("~"), ".hololinked")
        self.TCP_SOCKET_SEARCH_START_PORT = 60000
        self.TCP_SOCKET_SEARCH_END_PORT = 65535
        self.ALLOW_CORS = False
        self.DB_CONFIG_FILE = None
        self.USE_UVLOOP = False
        self.TRACE_MALLOC = False
        # self.VALIDATE_SCHEMA_ON_CLIENT = False
        self.VALIDATE_SCHEMAS = True
        self.ZMQ_CONTEXT = zmq.asyncio.Context()
        self.DEBUG = False
        self.LOG_LEVEL = logging.DEBUG if self.DEBUG else logging.INFO
        # self.USE_STRUCTLOG = True
        self.COLORED_LOGS = False
        self.ALLOW_PICKLE = False
        self.ALLOW_UNKNOWN_SERIALIZATION = False

        if not use_environment:
            return
        # environment variables overwrite config items
        file = os.environ.get("HOLOLINKED_CONFIG", None)
        if not file:
            warnings.warn("no environment file found although asked to load from one", UserWarning)
            return
        with open(file, "r") as file:
            config = json.load(file)  # type: dict[str, Any]
        for item, value in config.items():
            setattr(self, item, value)

    def setup(self):
        """actions to be done to reset configurations (not actions to be called)"""
        try:
            os.mkdir(self.TEMP_DIR)
            os.mkdir(os.path.join(self.TEMP_DIR, "sockets"))
            os.mkdir(os.path.join(self.TEMP_DIR, "logs"))
            os.mkdir(os.path.join(self.TEMP_DIR, "db"))
        except FileExistsError:
            pass
        from .logger import setup_logging

        # if self.USE_STRUCTLOG:
        setup_logging(log_level=self.LOG_LEVEL, colored_logs=self.COLORED_LOGS)

        set_global_event_loop_policy()
        if self.TRACE_MALLOC:
            tracemalloc.start()

    def copy(self):
        """returns a copy of this config as another object"""
        other = object.__new__(Configuration)
        for item in self.__slots__:
            setattr(other, item, getattr(self, item))
        return other

    def set(self, **kwargs):
        """sets multiple config values at once"""
        for item, value in kwargs.items():
            setattr(self, item, value)
        self.setup()

    def asdict(self):
        """returns this config as a regular dictionary"""
        return {item: getattr(self, item) for item in self.__slots__}

    def zmq_context(self) -> zmq.asyncio.Context:
        """
        Returns a global ZMQ async context. Use socket_class argument to retrieve
        a synchronous socket if necessary.
        """
        return self.ZMQ_CONTEXT

    def set_default_server_execution_context(
        self,
        invokation_timeout: int | None = None,
        execution_timeout: int | None = None,
        oneway: bool = False,
    ) -> None:
        """Sets the default server execution context for the application"""
        from .core.zmq.message import default_server_execution_context

        default_server_execution_context.invokationTimeout = invokation_timeout or 5
        default_server_execution_context.executionTimeout = execution_timeout or 5
        default_server_execution_context.oneway = oneway

    def set_default_thing_execution_context(
        self,
        fetch_execution_logs: bool = False,
    ) -> None:
        """Sets the default thing execution context for the application"""
        from .core.zmq.message import default_thing_execution_context

        default_thing_execution_context.fetchExecutionLogs = fetch_execution_logs

    def __del__(self):
        self.ZMQ_CONTEXT.term()


global_config = Configuration()

__all__ = ["global_config", "Configuration"]
