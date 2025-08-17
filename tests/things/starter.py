import asyncio
import typing, multiprocessing, threading, logging, queue
from hololinked.exceptions import BreakLoop
from hololinked.core.zmq.brokers import AsyncZMQServer
from hololinked.core.zmq.message import EXIT
from hololinked.core import ThingMeta, Thing
from hololinked.utils import get_current_async_loop


def run_thing_with_zmq_server(
    thing_cls: ThingMeta, 
    id: str, 
    protocols: typing.List[str] = ['IPC'], 
    tcp_socket_address: str = None,
    done_queue: typing.Optional[multiprocessing.Queue] = None,
    log_level: int = logging.WARN,
    prerun_callback: typing.Optional[typing.Callable] = None
) -> None:
    if prerun_callback:
        prerun_callback(thing_cls)
    thing = thing_cls(id=id, log_level=log_level) # type: Thing
    thing.run_with_zmq_server(
        zmq_protocols=protocols, 
        tcp_socket_address=tcp_socket_address
    )
    if done_queue is not None:
        done_queue.put(id)


def run_thing_with_http_server(
    thing_cls: ThingMeta, 
    id: str, 
    done_queue: queue.Queue = None,
    log_level: int = logging.WARN,
    prerun_callback: typing.Optional[typing.Callable] = None
) -> None:
    if prerun_callback:
        prerun_callback(thing_cls)
    thing = thing_cls(id=id, log_level=log_level) # type: Thing
    thing.run_with_http_server()
    if done_queue is not None:
        done_queue.put(id)   


def start_http_server(id : str) -> None:
    H = HTTPServer([id], log_level=logging.WARN)  
    H.listen()


def run_thing_with_zmq_server_forked(
    thing_cls: ThingMeta, 
    id: str, 
    log_level: int = logging.WARN,
    protocols: typing.List[str] = ['IPC'], 
    prerun_callback: typing.Optional[typing.Callable] = None,
    as_process: bool = True,
    done_queue: typing.Optional[multiprocessing.Queue] = None,
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
                            protocols=protocols,
                            tcp_socket_address=tcp_socket_address,
                            done_queue=done_queue,
                            log_level=log_level,
                            prerun_callback=prerun_callback
                        ), 
                        daemon=True
                    )
        P.start()
        # if not http_server:
        #     return P
        # multiprocessing.Process(
        #                 target=start_http_server, 
        #                 args=(id,), 
        #                 daemon=True
        #             ).start()
        # return P
    else:
        # if http_server:
        #     T = threading.Thread(
        #         target=run_thing_with_http_server,
        #         kwargs=dict(
        #             thing_cls=thing_cls,
        #             id=id,
        #             done_queue=done_queue,
        #             log_level=log_level,
        #             prerun_callback=prerun_callback
        #         )
        #     )
        # else:
        T = threading.Thread(
            target=run_thing_with_zmq_server,
            kwargs=dict(
                thing_cls=thing_cls,
                id=id,
                protocols=protocols,
                tcp_socket_address=tcp_socket_address,
                done_queue=done_queue,
                log_level=log_level,
                prerun_callback=prerun_callback
            ), daemon=True
        )
        T.start()
        return T


    
def run_zmq_server(server: AsyncZMQServer, owner, done_queue: multiprocessing.Queue) -> None:
    event_loop = get_current_async_loop()
    async def run():
        while True:
            try:
                messages = await server.async_recv_requests()           
                owner.last_server_message = messages[0]
                for message in messages:
                    if message.type == EXIT:
                        server.exit()
                        return
                await asyncio.sleep(0.01)
            except BreakLoop:
                break
    event_loop.run_until_complete(run())
    event_loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(event_loop)))
    if done_queue:
        done_queue.put(True)
