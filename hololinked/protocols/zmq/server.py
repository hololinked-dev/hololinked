import asyncio
import typing
import zmq

from .brokers import AsyncZMQServer
from ...constants import ZMQ_TRANSPORTS
from ...utils import get_current_async_loop
from ...server.thing import Thing
from ...server.rpc_server import RPCServer



class ZMQServer(RPCServer):

    def __init__(self, *, 
                id: str, 
                things: typing.List["Thing"],
                context: zmq.asyncio.Context | None = None, 
                transports: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.IPC,
                **kwargs
            ) -> None:
        self.ipc_server = self.tcp_server = self.event_publisher = None
        super().__init__(id=id, things=things, context=context, **kwargs)

        
        if isinstance(transports, str): 
            transports = [transports]
        elif not isinstance(transports, list): 
            raise TypeError(f"unsupported transport type : {type(transports)}")
        tcp_socket_address = kwargs.pop('tcp_socket_address', None)
        event_publisher_protocol = None 
        
        # initialise every externally visible protocol          
        if ZMQ_TRANSPORTS.TCP in transports or "TCP" in transports:
            self.tcp_server = AsyncZMQServer(
                                id=self.id, 
                                context=self.context, 
                                transport=ZMQ_TRANSPORTS.TCP,
                                socket_address=tcp_socket_address,
                                **kwargs
                            )        
            event_publisher_protocol = ZMQ_TRANSPORTS.TCP
        if ZMQ_TRANSPORTS.IPC in transports or "IPC" in transports: 
            self.ipc_server = AsyncZMQServer(
                                id=self.id, 
                                context=self.context, 
                                transport=ZMQ_TRANSPORTS.IPC,
                                **kwargs
                            )        
            
            event_publisher_protocol = ZMQ_TRANSPORTS.IPC if not event_publisher_protocol else event_publisher_protocol           
        event_publisher_protocol = "IPC" if not event_publisher_protocol else event_publisher_protocol    

    
    def run_external_message_listener(self) -> None:
        eventloop = get_current_async_loop()
       
        if self.ipc_server is not None:
            eventloop.call_soon(lambda : asyncio.create_task(self.recv_and_dispatch_requests(self.ipc_server)))
        if self.tcp_server is not None:
            eventloop.call_soon(lambda : asyncio.create_task(self.recv_and_dispatch_requests(self.tcp_server)))
        super().run_external_message_listener()


    def stop(self) -> None:
        if self.ipc_server is not None:
            self.ipc_server.stop_polling()
        if self.tcp_server is not None:
            self.tcp_server.stop_polling()
        super().stop()


    def exit(self) -> None:
        try:
            self.stop()
            if self.ipc_server is not None:
                self.ipc_server.exit()
            if self.tcp_server is not None:
                self.tcp_server.exit()
            if self.req_rep_server is not None:
                self.req_rep_server.exit()
            # if self.event_publisher is not None:
            #     self.event_publisher.exit()
        except:
            pass 
        if self._terminate_context:
            self.context.term()
        self.logger.info("terminated context of socket '{}' of type '{}'".format(self.id, self.__class__))
    

