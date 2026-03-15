import asyncio

import aiocoap

from aiocoap.resource import Resource, Site

from hololinked.server import BaseProtocolServer


class CoAPServer(BaseProtocolServer):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

        super().__init__()

    def add_resource(self, path: str, resource: Resource):
        """Add a CoAP resource to the server at the specified path"""
        self.root.add_resource(path, resource)

    async def setup(self) -> None:
        # This method should not block, just create side-effects
        self.root = Site()
        self.root.add_resource(
            (".well-known", "core"), Resource()
        )  # add a default resource for discovery, this is only an example
        await aiocoap.Context.create_server_context(self.root, bind=(self.host, self.port))

    async def start(self) -> None:
        # This method should not block, just create side-effects
        # await self.setup()  # call setup() here, this is only an example
        await asyncio.get_running_loop().create_future()
