




class TestRPCBroker:
    

    @classmethod
    def setUpServer(self):
        self.server = AsyncZMQServer(
                                    id=self.server_id,
                                    logger=self.logger
                                )
    """
    Base class: BaseZMQ, BaseAsyncZMQ, BaseSyncZMQ
    Servers: BaseZMQServer, AsyncZMQServer, ZMQServerPool
    Clients: BaseZMQClient, SyncZMQClient, AsyncZMQClient, MessageMappedZMQClientPool
    """

    @classmethod
    def setUpClient(self):
        self.client = SyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False
                            )
        

    @classmethod
    def startServer(self):
        self._server_thread = threading.Thread(
                                            target=run_server, 
                                            args=(self.server, self, self.done_queue),
                                            daemon=True
                                        )
        self._server_thread.start()