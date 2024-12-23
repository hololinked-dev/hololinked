



class ZMQServer:
    

    def __init__(self, *, id : str, 
                things : typing.Union[Thing, typing.List[typing.Union[Thing]]], # type: ignore - requires covariant types
                protocols : typing.Union[ZMQ_TRANSPORTS, str, typing.List[ZMQ_TRANSPORTS]] = ZMQ_TRANSPORTS.IPC, 
                poll_timeout = 25, context : typing.Union[zmq.asyncio.Context, None] = None, 
                **kwargs
            ) -> None:
        self.inproc_server = self.ipc_server = self.tcp_server = self.event_publisher = None
        
        if isinstance(protocols, str): 
            protocols = [protocols]
        elif not isinstance(protocols, list): 
            raise TypeError(f"unsupported protocols type : {type(protocols)}")
        tcp_socket_address = kwargs.pop('tcp_socket_address', None)
        event_publisher_protocol = None 
        
        # initialise every externally visible protocol          
        if ZMQ_TRANSPORTS.TCP in protocols or "TCP" in protocols:
            self.tcp_server = AsyncZMQServer(id=self.id, server_type=ServerTypes.RPC, 
                                    context=self.context, transport=ZMQ_TRANSPORTS.TCP, poll_timeout=poll_timeout, 
                                    socket_address=tcp_socket_address, **kwargs)
            self.poller.register(self.tcp_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_TRANSPORTS.TCP
        if ZMQ_TRANSPORTS.IPC in protocols or "IPC" in protocols: 
            self.ipc_server = AsyncZMQServer(id=self.id, server_type=ServerTypes.RPC, 
                                    context=self.context, transport=ZMQ_TRANSPORTS.IPC, poll_timeout=poll_timeout, **kwargs)
            self.poller.register(self.ipc_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_TRANSPORTS.IPC if not event_publisher_protocol else event_publisher_protocol           
            event_publisher_protocol = "IPC" if not event_publisher_protocol else event_publisher_protocol    

        self.poller = zmq.asyncio.Poller()
        self.poll_timeout = poll_timeout

    
    @property
    def poll_timeout(self) -> int:
        """
        socket polling timeout in milliseconds greater than 0. 
        """
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(("polling period must be an integer greater than 0, not {}.",
                              "Value is considered in milliseconds.".format(value)))
        self._poll_timeout = value 