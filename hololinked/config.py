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

from typing import Any  # noqa: F401

import zmq.asyncio

from .utils import generate_main_script_log_filename, set_global_event_loop_policy


class Configuration:
    """
    Allows to auto apply common settings used throughout the package, instead of passing these settings as arguments.
    Import `global_config` variable instead of instantiating this class. Please check `global_config` docstring for supported values
    or [website documentation](https://docs.hololinked.dev/api-reference/global-config/).

    This implementation needs to be improved in general. Consider opening an issue
    if you have suggestions at [GitHub](https://github.com/hololinked-dev/hololinked/issues).
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
        # internal
        "_sockets_folder",
        "_secrets_folder",
        "_logs_folder",
        "_db_folder",
    ]

    def __init__(self, app_name: str | None = None):
        self.app_name = app_name
        self._sockets_folder = "sockets"
        self._secrets_folder = "secrets"
        self._logs_folder = "logs"
        self._db_folder = "db"
        self.load_variables()

    def load_variables(self):
        """Set default values. This method is called during `__init__`"""
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
        self.LOG_FILENAME = os.path.join(self.TEMP_DIR_LOGS, generate_main_script_log_filename(self.app_name))
        self.ROTATE_LOG_FILES = True
        self.LOGFILE_BACKUP_COUNT = 14
        # Add the filename of the main script importing this module
        self.ALLOW_PICKLE = False
        self.ALLOW_UNKNOWN_SERIALIZATION = False

        self.setup()

    def setup(self):
        """
        Actions to be done to recreate global configuration state after changing config values.
        Called after `load_variables` and `set` methods.

        Please call this method after changing config values directly specific to logging or event loop policy
        """
        self.setup_temp_dirs()

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

    @property
    def TEMP_DIR_SOCKETS(self) -> str:
        """returns the temporary directory path for IPC sockets"""
        return os.path.join(self.TEMP_DIR, self._sockets_folder)

    @property
    def TEMP_DIR_LOGS(self) -> str:
        """returns the temporary directory path for log files"""
        return os.path.join(self.TEMP_DIR, self._logs_folder)

    @property
    def TEMP_DIR_DB(self) -> str:
        """returns the temporary directory path for database files"""
        return os.path.join(self.TEMP_DIR, self._db_folder)

    @property
    def TEMP_DIR_SECRETS(self) -> str:
        """returns the temporary directory path for secret files"""
        return os.path.join(self.TEMP_DIR, self._secrets_folder)

    def setup_temp_dirs(self) -> None:
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

    def set_temp_dir(self, path: str) -> None:
        """sets the base directory path for temporary files and application data (sockets, logs, databases, secrets)"""
        self.TEMP_DIR = path
        self.setup_temp_dirs()

    def set_sockets_folders(self, path: str) -> None:
        """sets the temporary directory path for IPC sockets"""
        self._sockets_folder = path
        self.setup_temp_dirs()

    def set_logs_folder(self, path: str) -> None:
        """sets the temporary directory path for log files"""
        self._logs_folder = path
        self.setup_temp_dirs()

    def set_db_folder(self, path: str) -> None:
        """sets the temporary directory path for database files"""
        self._db_folder = path
        self.setup_temp_dirs()

    def set_secrets_folder(self, path: str) -> None:
        """sets the temporary directory path for secret files"""
        self._secrets_folder = path
        self.setup_temp_dirs()

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


global_config = Configuration()
"""
Allows to auto apply common settings used throughout the package, instead of passing these settings as arguments.
Import `global_config` variable instead of instantiating this class.

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
"""

__all__ = ["global_config", "Configuration"]
