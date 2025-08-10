import asyncio
import typing
import zmq
import zmq.asyncio

from ..constants import ZMQ_TRANSPORTS
from ..utils import get_current_async_loop
from ..core.thing import Thing
from ..core.zmq.brokers import AsyncEventConsumer, AsyncZMQServer, EventPublisher
from ..core.zmq.rpc_server import RPCServer



class ZMQServer(RPCServer):

    def __init__(self, *, 
                id: str, 
                things: typing.List["Thing"],
                context: zmq.asyncio.Context | None = None, 
                transports: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.IPC,
                **kwargs
            ) -> None:
        self.ipc_server = self.tcp_server = None
        self.ipc_event_publisher = self.tcp_event_publisher = self.inproc_events_proxy = None
        super().__init__(id=id, things=things, context=context, **kwargs)

        if isinstance(transports, str): 
            transports = [transports]
        elif not isinstance(transports, list): 
            raise TypeError(f"unsupported transport type : {type(transports)}")
        for index, transport in enumerate(transports):
            transports[index] = transport.upper() if isinstance(transport, str) else transport

        tcp_socket_address = kwargs.pop('tcp_socket_address', None)

        # initialise every externally visible protocol          
        if ZMQ_TRANSPORTS.TCP in transports or "TCP" in transports:
            self.tcp_server = AsyncZMQServer(
                                id=self.id, 
                                context=self.context, 
                                transport=ZMQ_TRANSPORTS.TCP,
                                socket_address=tcp_socket_address,
                                **kwargs
                            )        
            host, port = self.tcp_server.socket_address.rsplit(':', 1)
            new_port = int(port) + 1 # try the next port for the event publisher
            tcp_socket_address = f"{host}:{new_port}"
            self.tcp_event_publisher = EventPublisher(
                                            id=f'{self.id}/event-publisher',
                                            context=self.context,
                                            transport=ZMQ_TRANSPORTS.TCP,
                                            socket_address=tcp_socket_address,
                                            **kwargs
                                        )       
        if ZMQ_TRANSPORTS.IPC in transports or "IPC" in transports: 
            self.ipc_server = AsyncZMQServer(
                                id=self.id, 
                                context=self.context, 
                                transport=ZMQ_TRANSPORTS.IPC,
                                **kwargs
                            )        
            self.ipc_event_publisher = EventPublisher(
                                            id=f'{self.id}/event-publisher',
                                            context=self.context,
                                            transport=ZMQ_TRANSPORTS.IPC,
                                            **kwargs
                                        )
        if self.ipc_event_publisher is not None or self.tcp_event_publisher is not None:
            self.inproc_events_proxy = AsyncEventConsumer(
                                            id=f'{self.id}/event-proxy',
                                            event_unique_identifier="",
                                            socket_address=self.event_publisher.socket_address,
                                            context=self.context,
                                            **kwargs
                                        )
           
    
    def run_zmq_request_listener(self) -> None:
        # doc in parent class
        eventloop = get_current_async_loop()
        if self.ipc_server is not None:
            eventloop.call_soon(lambda : asyncio.create_task(self.recv_requests_and_dispatch_jobs(self.ipc_server)))
        if self.tcp_server is not None:
            eventloop.call_soon(lambda : asyncio.create_task(self.recv_requests_and_dispatch_jobs(self.tcp_server)))
        if self.inproc_events_proxy is not None:
            eventloop.call_soon(lambda : asyncio.create_task(self.tunnel_events_from_inproc()))
        super().run_zmq_request_listener()

    
    async def tunnel_events_from_inproc(self) -> None:
        if not self.inproc_events_proxy:
            return
        self.inproc_events_proxy.subscribe()
        while True:
            try:
                event = await self.inproc_events_proxy.receive(raise_interrupt_as_exception=True)
                if self.ipc_event_publisher is not None:
                    self.ipc_event_publisher.socket.send_multipart(event.byte_array)
                    # print(f"sent event to ipc publisher {event.byte_array}")
                if self.tcp_event_publisher is not None:
                    self.tcp_event_publisher.socket.send_multipart(event.byte_array)
                    # print(f"sent event to tcp publisher {event.byte_array}")
            except ConnectionAbortedError:
                break
            except Exception as e:
                self.logger.error(f"error in tunneling events from inproc: {e}")
                break


    def stop(self) -> None:
        if self.ipc_server is not None:
            self.ipc_server.stop_polling()
        if self.tcp_server is not None:
            self.tcp_server.stop_polling()
        if self.inproc_events_proxy is not None:
            get_current_async_loop().call_soon(lambda : asyncio.create_task(self.inproc_events_proxy.interrupt()))
        super().stop()


    def exit(self) -> None:
        try:
            self.stop()
            if self.ipc_server is not None:
                self.ipc_server.exit()
                self.ipc_event_publisher.exit()
            if self.tcp_server is not None:
                self.tcp_server.exit()
                self.tcp_event_publisher.exit()
            if self.req_rep_server is not None:
                self.req_rep_server.exit()
            if self.event_publisher is not None:
                self.event_publisher.exit()
            if self.inproc_events_proxy is not None:
                self.inproc_events_proxy.exit()
        except Exception as ex:
            self.logger.warning(f"Exception occurred while exiting the server - {str(ex)}")
            

    def __str__(self):
        parts = [f"ZMQServer(\n\tid: {self.id}"]
        for name in [
            "ipc_server", "tcp_server", "req_rep_server", "ipc_event_publisher",
            "tcp_event_publisher", "event_publisher", "inproc_events_proxy"
        ]:
            obj = getattr(self, name, None)
            if obj is not None:
                type_name = type(obj).__name__
                parts.append(f"{name}: {getattr(obj, 'socket_address', None)} ({type_name})")
            else:
                parts.append(f"{name}: None")
        paths = "\n\t".join(parts)
        paths += "\n)"
        return paths

