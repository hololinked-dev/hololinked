import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from hololinked.server.http import HTTPServer
from hololinked.server.zmq import ZMQServer
from hololinked.serializers import Serializers
from hololinked.config import global_config
from things import TestThing

global_config.DEBUG = True

thing = TestThing(id="example-test")

Serializers.register_for_object(TestThing.db_init_int_prop, Serializers.pickle)
Serializers.register_for_object(TestThing.set_non_remote_number_prop, Serializers.msgpack)
Serializers.register_for_object(TestThing.get_non_remote_number_prop, Serializers.msgpack)
Serializers.register_for_object(TestThing.numpy_array_prop, Serializers.msgpack)
Serializers.register_for_object(TestThing.numpy_action, Serializers.msgpack)

# thing.run(
#     access_points=[
#         ("ZMQ", "IPC"),
#         ("HTTP", 8080),
#     ]
# )

http_server = HTTPServer(port=9000)
zmq_server = ZMQServer(id="example-test-server", things=[thing], access_points="IPC")
thing.run(servers=[http_server, zmq_server])
