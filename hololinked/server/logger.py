import logging 
import typing 
import datetime
import threading
import asyncio
import time 
from collections import deque

from .constants import HTTP_METHODS
from .events import Event
from .properties import List
from .properties import Integer, Number
from .thing import Thing as RemoteObject
from .actions import action as remote_method



class ListHandler(logging.Handler):
    """
    Log history handler. Add and remove this handler to hold a bunch of specific logs. Currently used by execution context
    within ``EventLoop`` where one can fetch the execution logs while an action is being executed. 
    """

    def __init__(self, log_list : typing.Optional[typing.List] = None):
        super().__init__()
        self.log_list : typing.List[typing.Dict] = [] if not log_list else log_list
    
    def emit(self, record : logging.LogRecord):
        log_entry = self.format(record)
        self.log_list.insert(0, {
            'level' : record.levelname,
            'timestamp' : datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            'thread_id' : threading.get_ident(),
            'message' : record.msg
        })


log_message_schema = {
    "type" : "object",
    "properties" : {
        "level" : {"type" : "string" },
        "timestamp" : {"type" : "string" },
        "thread_id" : {"type" : "integer"},
        "message" : {"type" : "string"}
    },
    "required" : ["level", "timestamp", "thread_id", "message"],
    "additionalProperties" : False
}


class RemoteAccessHandler(logging.Handler, RemoteObject):
    """
    Log handler with remote access attached to ``Thing``'s logger if logger_remote_access is True.
    The schema of the pushed logs are a list containing a dictionary for each log message with 
    the following fields: 

    .. code-block:: python

        {
            "level" : str,
            "timestamp" : str,
            "thread_id" : int,
            "message" : str
        }
    """

    def __init__(self, instance_name : str = 'logger', maxlen : int = 500, stream_interval : float = 1.0, 
                    **kwargs) -> None:
        """
        Parameters
        ----------
        instance_name: str, default 'logger'
            instance name of the object, generally only one instance per ``Thing`` necessary, therefore defaults to
            'logger'
        maxlen: int, default 500
            history of log entries to store in RAM
        stream_interval: float, default 1.0
            when streaming logs using log-events endpoint, this value is the stream interval.
        **kwargs:
            len_debug: int
                length of debug logs, default maxlen/5
            len_info: int
                length of info logs, default maxlen/5
            len_warn: int
                length of warn logs, default maxlen/5
            len_error: int
                length of error logs, default maxlen/5
            len_critical: int
                length of critical logs, default maxlen/5
        """
        logging.Handler.__init__(self)
        RemoteObject.__init__(self, instance_name=instance_name, **kwargs)
        self.set_maxlen(maxlen, **kwargs)
        self.stream_interval = stream_interval
        self.diff_logs = []
        self._push_events = False
        self._events_thread = None

    log_events = Event(friendly_name='log-events', doc='stream logs', 
                schema=log_message_schema)

    stream_interval = Number(default=1.0, bounds=(0.025, 60.0), crop_to_bounds=True, step=0.05,
                            doc="interval at which logs should be published to a client.")
    
    def get_maxlen(self):
        return self._maxlen 
    
    def set_maxlen(self, value, **kwargs):
        self._maxlen = value
        self._debug_logs = deque(maxlen=kwargs.pop('len_debug', int(value/5)))
        self._info_logs = deque(maxlen=kwargs.pop('len_info', int(value/5)))
        self._warn_logs = deque(maxlen=kwargs.pop('len_warn', int(value/5)))
        self._error_logs = deque(maxlen=kwargs.pop('len_error', int(value/5)))
        self._critical_logs = deque(maxlen=kwargs.pop('len_critical', int(value/5)))
        self._execution_logs = deque(maxlen=value)

    maxlen = Integer(default=100, bounds=(1, None), crop_to_bounds=True, 
                fget=get_maxlen, fset=set_maxlen, doc="length of execution log history to store")


    @remote_method()
    def push_events(self, scheduling : str = 'threaded', stream_interval : float = 1) -> None:
        """
        Push events to client. This method is intended to be called remotely for
        debugging the Thing. 
       
        Parameters
        ----------
        scheduling: str
            'threaded' or 'async. threaded starts a new thread, async schedules a task to the 
            main event loop.
        stream_interval: float
            interval of push in seconds. 
        """
        self.stream_interval = stream_interval 
        if scheduling == 'asyncio':
            asyncio.get_event_loop().call_soon(lambda : asyncio.create_task(self._async_push_diff_logs()))
        elif scheduling == 'threading':
            if self._events_thread is not None: # dont create again if one is already running
                self._events_thread = threading.Thread(target=self._push_diff_logs)
                self._events_thread.start()
        else:
            raise ValueError(f"scheduling can only be 'threaded' or 'async'. Given value {scheduling}")

    @remote_method()
    def stop_events(self) -> None:
        """
        stop pushing events
        """
        self._push_events = False 
        if self._events_thread: # coroutine variant will resolve automatically 
            self._events_thread.join()
            self._owner.logger.debug(f"joined log event source with thread-id {self._events_thread.ident}.")
            self._events_thread = None
    
    def emit(self, record : logging.LogRecord):
        log_entry = self.format(record)
        info = {
            'level' : record.levelname,
            'timestamp' : datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            'thread_id' : threading.get_ident(),
            'message' : record.msg
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
                self.event.push(self.diff_logs) 
                self.diff_logs.clear()
        # give time to collect final logs with certainty
        self._owner.logger.info(f"ending log event source with thread-id {threading.get_ident()}.")

    async def _async_push_diff_logs(self) -> None:
        while self._push_events:
            await asyncio.sleep(self.stream_interval)
            self.event.push(self.diff_logs) 
            self.diff_logs.clear()
        self._owner.logger.info(f"ending log events.")
           
    debug_logs = List(default=[], readonly=True, fget=lambda self: self._debug_logs,
                            doc="logs at logging.DEBUG level")
    
    warn_logs = List(default=[], readonly=True, fget=lambda self: self._warn_logs,
                            doc="logs at logging.WARN level")
    
    info_logs = List(default=[], readonly=True, fget=lambda self: self._info_logs,
                            doc="logs at logging.INFO level")
       
    error_logs = List(default=[], readonly=True, fget=lambda self: self._error_logs,
                            doc="logs at logging.ERROR level")
 
    critical_logs = List(default=[], readonly=True, fget=lambda self: self._critical_logs,
                            doc="logs at logging.CRITICAL level")
  
    execution_logs = List(default=[], readonly=True, fget=lambda self: self._execution_logs,
                            doc="logs at all levels accumulated in order of collection/execution")
    


__all__ = [
    ListHandler.__name__, 
    RemoteAccessHandler.__name__
]