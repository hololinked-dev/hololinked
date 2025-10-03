import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from hololinked.server.http import HTTPServer
from hololinked.server.zmq import ZMQServer
from hololinked.config import global_config
from things import TestThing

global_config.DEBUG = True

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
