from hololinked.core import Thing
from hololinked.constants import Operations
from hololinked.server.http import HTTPServer
from hololinked.server.zmq import ZMQServer
from things import TestThing

thing = TestThing(id="example-test")
# thing.run(
#     access_points=[
#         ("ZMQ", "IPC"),
#         ("HTTP", 8080),
#     ]
# )


http_server = HTTPServer(port=9000)
zmq_server = ZMQServer(id="example-test-server", things=[thing], access_points="IPC")
thing.run(servers=[http_server, zmq_server])
