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

import logging
import os
import shutil
import tracemalloc
import warnings

from pathlib import Path
from typing import Any  # noqa: F401

import zmq.asyncio

import __main__

from .utils import (
    get_sanitized_filename_from_random_string,
    set_global_event_loop_policy,
)


class Configuration:
    """
    Allows to auto apply common settings used throughout the package, instead of passing these settings as arguments.
    Import `global_config` variable instead of instantitation this class.

    ```python
    from hololinked.config import global_config

    global_config.TEMP_DIR = "/my/temp/dir"
    global_config.ALLOW_CORS = True
    global_config.setup()  # Important to call setup() after changing values

    class MyThing(Thing):
        ...
    ```

    Values are not type checked and are usually mutable in runtime, except:

    - logging setup
    - ZMQ context
    - global event loop policy

    which refresh the global state. Keys of JSON file must correspond to supported value name.

    Supported values are -

    `TEMP_DIR` - system temporary directory to store temporary files like IPC sockets.
    default - `~/.hololinked` (`.hololinked` under home directory).

    `TCP_SOCKET_SEARCH_START_PORT` - starting port number for automatic port searching
    for TCP socket binding, used for event addresses. default `60000`.

    `TCP_SOCKET_SEARCH_END_PORT` - ending port number for automatic port searching
    for TCP socket binding, used for event addresses. default `65535`.

    `DB_CONFIG_FILE` - file path for database configuration. default `None`.

    `USE_UVLOOP` - signicantly faster event loop for Linux systems. Reads data from network faster. default `False`.

    `TRACE_MALLOC` - whether to trace memory allocations using tracemalloc module. default `False`.

    `VALIDATE_SCHEMAS` - whether to validate JSON schema supplied for properties, actions and events
    (not validation of payload, but validation of schema itself). default `True`.

    `DEBUG` - whether to print debug logs. default `False`.

    `LOG_LEVEL` - logging level to use. default `logging.INFO`, `logging.DEBUG` if `DEBUG` is `True`.

    `COLORED_LOGS` - whether to use colored logs in console. default `False`.

    `ALLOW_PICKLE` - whether to allow pickle serialization/deserialization. default `False`.

    `ALLOW_UNKNOWN_SERIALIZATION` - whether to allow unknown serialization formats, specifically from clients. default `False`.

    Parameters
    ----------
    use_environment: bool
        load files from JSON file specified under environment
    """

    __slots__ = [
        "app_name",
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
        "USE_LOG_FILE",
        "LOG_FILENAME",
        "ROTATE_LOG_FILES",
        "LOGFILE_BACKUP_COUNT",
        # "USE_STRUCTLOG",
        "COLORED_LOGS",
        # serializers
        "ALLOW_PICKLE",
        "ALLOW_UNKNOWN_SERIALIZATION",
    ]

    def __init__(self, app_name: str | None = None):
        self.app_name = app_name
        self.load_variables()

    def load_variables(self):
        """
        set default values & use the values from environment file.
        Set `use_environment` to `False` to not use environment file. This method is called during `__init__`.
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
        self.USE_LOG_FILE = False
        self.LOG_FILENAME = os.path.join(self.TEMP_DIR_LOGS, self._main_script_filename)
        self.ROTATE_LOG_FILES = True
        self.LOGFILE_BACKUP_COUNT = 14
        # Add the filename of the main script importing this module
        self.ALLOW_PICKLE = False
        self.ALLOW_UNKNOWN_SERIALIZATION = False

        self.setup()

    def setup(self):
        """
        actions to be done to recreate global configuration state after changing config values.
        Called after `load_variables` and `set` methods.
        """
        for directory in [
            self.TEMP_DIR,
            self.TEMP_DIR_SOCKETS,
            self.TEMP_DIR_LOGS,
            self.TEMP_DIR_DB,
            self.TEMP_DIR_SECRETS,
        ]:
            try:
                os.mkdir(directory)
            except FileExistsError:
                pass
            except PermissionError:
                warnings.warn(f"permission denied to create directory {directory}", UserWarning)

        set_global_event_loop_policy(self.USE_UVLOOP)
        if self.TRACE_MALLOC:
            tracemalloc.start()

        from .logger import setup_logging

        self.LOG_LEVEL = logging.DEBUG if self.DEBUG else self.LOG_LEVEL

        # if self.USE_STRUCTLOG: # no other option for now
        setup_logging(
            log_level=self.LOG_LEVEL,
            colored_logs=self.COLORED_LOGS,
            log_file=self.LOG_FILENAME if self.USE_LOG_FILE else None,
            rotate_log_files=self.ROTATE_LOG_FILES,
            logfile_backup_count=self.LOGFILE_BACKUP_COUNT,
        )

    def copy(self):
        """returns a copy of this config as another object"""
        other = object.__new__(Configuration)
        for item in self.__slots__:
            setattr(other, item, getattr(self, item))
        return other

    def set(self, **kwargs):
        """
        sets multiple config values at once, and recreates necessary global states.
        `load_variables` sets default values first, then overwrites with environment file values.
        This method only overwrites the specified values.
        """
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

    def cleanup_temp_dirs(self, cleanup_databases: bool = False) -> None:
        """
        Cleans up temporary directories used by hololinked, all log files and IPC sockets are removed.
        If `cleanup_databases` is `True`, database files are also removed.
        """
        directories = [self.TEMP_DIR_SOCKETS, self.TEMP_DIR_LOGS]
        if cleanup_databases:
            directories.append(self.TEMP_DIR_DB)
        for directory in directories:
            try:
                shutil.rmtree(directory)
            except FileNotFoundError:
                pass
            except PermissionError:
                warnings.warn(f"permission denied to cleanup directory {directory}", UserWarning)

    def __del__(self):
        self.ZMQ_CONTEXT.term()

    @property
    def TEMP_DIR_SOCKETS(self) -> str:
        """returns the temporary directory path for IPC sockets"""
        return os.path.join(self.TEMP_DIR, "sockets")

    @property
    def TEMP_DIR_LOGS(self) -> str:
        """returns the temporary directory path for log files"""
        return os.path.join(self.TEMP_DIR, "logs")

    @property
    def TEMP_DIR_DB(self) -> str:
        """returns the temporary directory path for database files"""
        return os.path.join(self.TEMP_DIR, "db")

    @property
    def TEMP_DIR_SECRETS(self) -> str:
        """returns the temporary directory path for secret files"""
        return os.path.join(self.TEMP_DIR, "secrets")

    @property
    def _main_script_filename(self) -> str | None:
        """returns the main script filename if available"""
        if not self.app_name:
            file = getattr(__main__, "__file__", None)
            if not file:
                filename = Path.cwd().name
            else:
                file = os.path.splitext(os.path.basename(file))
                filename = file[0]
        else:
            filename = self.app_name
        if filename:
            return get_sanitized_filename_from_random_string(filename, extension="log")
        return "hololinked.log"


global_config = Configuration()

__all__ = ["global_config", "Configuration"]
