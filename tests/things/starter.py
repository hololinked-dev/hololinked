import asyncio
import typing, multiprocessing, threading, logging, queue
from hololinked.exceptions import BreakLoop
from hololinked.protocols.zmq.brokers import AsyncZMQServer
from hololinked.protocols.zmq.message import EXIT
from hololinked.server import ThingMeta, Thing
from hololinked.utils import get_current_async_loop


def run_thing(
    thing_cls : ThingMeta, 
    instance_name : str, 
    protocols : typing.List[str] = ['IPC'], 
    tcp_socket_address : str = None,
    done_queue : typing.Optional[multiprocessing.Queue] = None,
    log_level : int = logging.WARN,
    prerun_callback : typing.Optional[typing.Callable] = None
) -> None:
    if prerun_callback:
        prerun_callback(thing_cls)
    thing = thing_cls(instance_name=instance_name, log_level=log_level) # type: Thing
    thing.run(zmq_protocols=protocols, tcp_socket_address=tcp_socket_address)
    if done_queue is not None:
        done_queue.put(instance_name)


def run_thing_with_http_server(
    thing_cls : ThingMeta, 
    instance_name : str, 
    done_queue : queue.Queue = None,
    log_level : int = logging.WARN,
    prerun_callback : typing.Optional[typing.Callable] = None
) -> None:
    if prerun_callback:
        prerun_callback(thing_cls)
    thing = thing_cls(instance_name=instance_name, log_level=log_level) # type: Thing
    thing.run_with_http_server()
    if done_queue is not None:
        done_queue.put(instance_name)   


def start_http_server(instance_name : str) -> None:
    H = HTTPServer([instance_name], log_level=logging.WARN)  
    H.listen()


def start_thing_forked(
    thing_cls : ThingMeta, 
    instance_name : str, 
    protocols : typing.List[str] = ['IPC'], 
    tcp_socket_address : str = None,
    done_queue : typing.Optional[multiprocessing.Queue] = None,
    log_level : int = logging.WARN,
    prerun_callback : typing.Optional[typing.Callable] = None,
    as_process : bool = True,
    http_server : bool = False
):
    if as_process:
        P = multiprocessing.Process(
                        target=run_thing,
                        kwargs=dict(
                            thing_cls=thing_cls,
                            instance_name=instance_name,
                            protocols=protocols,
                            tcp_socket_address=tcp_socket_address,
                            done_queue=done_queue,
                            log_level=log_level,
                            prerun_callback=prerun_callback
                        ), daemon=True
                    )
        P.start()
        if not http_server:
            return P
        multiprocessing.Process(
                        target=start_http_server, 
                        args=(instance_name,), 
                        daemon=True
                    ).start()
        return P
    else:
        if http_server:
            T = threading.Thread(
                target=run_thing_with_http_server,
                kwargs=dict(
                    thing_cls=thing_cls,
                    instance_name=instance_name,
                    done_queue=done_queue,
                    log_level=log_level,
                    prerun_callback=prerun_callback
                )
            )
        else:
            T = threading.Thread(
                target=run_thing,
                kwargs=dict(
                    thing_cls=thing_cls,
                    instance_name=instance_name,
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
                        return
                await asyncio.sleep(0.01)
            except BreakLoop:
                break
    event_loop.run_until_complete(run())
    if done_queue:
        done_queue.put(True)