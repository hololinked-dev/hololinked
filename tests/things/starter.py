import logging
import multiprocessing
import queue
import threading
import typing

from hololinked.core import ThingMeta
from hololinked.logger import setup_logging


def run_thing_with_zmq_server(
    thing_cls: ThingMeta,
    id: str,
    access_points: typing.List[str] = ["IPC"],
    done_queue: typing.Optional[multiprocessing.Queue] = None,
    log_level: int = logging.WARN,
    prerun_callback: typing.Optional[typing.Callable] = None,
) -> None:
    setup_logging(log_level=log_level)
    if prerun_callback:
        prerun_callback(thing_cls)
    thing = thing_cls(id=id, log_level=log_level)  # type: Thing
    thing.run_with_zmq_server(access_points=access_points)
    if done_queue is not None:
        done_queue.put(id)


def run_thing_with_http_server(
    thing_cls: ThingMeta,
    id: str,
    done_queue: queue.Queue = None,
    log_level: int = logging.WARN,
    prerun_callback: typing.Optional[typing.Callable] = None,
) -> None:
    if prerun_callback:
        prerun_callback(thing_cls)
    thing = thing_cls(id=id, log_level=log_level)  # type: Thing
    thing.run_with_http_server()
    if done_queue is not None:
        done_queue.put(id)


def run_thing_with_zmq_server_forked(
    thing_cls: ThingMeta,
    id: str,
    access_points: typing.List[str] = ["IPC"],
    done_queue: typing.Optional[multiprocessing.Queue] = None,
    log_level: int = logging.WARN,
    prerun_callback: typing.Optional[typing.Callable] = None,
    as_process: bool = True,
) -> typing.Union[multiprocessing.Process, threading.Thread]:
    """
    run a Thing in a ZMQ server by forking from main process or thread.

    Parameters:
    -----------
    thing_cls: ThingMeta
        The class of the Thing to be run.
    id: str
        The id of the Thing to be run.
    log_level: int
        The log level to be used for the Thing. Default is logging.WARN.
    protocols: list of str
        The ZMQ protocols to be used for the Thing. Default is ['IPC'].
    tcp_socket_address: str
        The TCP socket address to be used for the Thing. Default is None.
    prerun_callback: callable
        A callback function to be called before running the Thing. Default is None.
    as_process: bool
        Whether to run the Thing in a separate process or thread. Default is True (as process).
    done_queue: multiprocessing.Queue
        A queue to be used for communication between processes. Default is None.
    """

    if as_process:
        P = multiprocessing.Process(
            target=run_thing_with_zmq_server,
            kwargs=dict(
                thing_cls=thing_cls,
                id=id,
                access_points=access_points,
                done_queue=done_queue,
                log_level=log_level,
                prerun_callback=prerun_callback,
            ),
            daemon=True,
        )
        P.start()
        return P
    else:
        T = threading.Thread(
            target=run_thing_with_zmq_server,
            kwargs=dict(
                thing_cls=thing_cls,
                id=id,
                access_points=access_points,
                done_queue=done_queue,
                log_level=log_level,
                prerun_callback=prerun_callback,
            ),
            daemon=True,
        )
        T.start()
        return T
