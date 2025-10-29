import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from hololinked.server.http import HTTPServer
from hololinked.server.zmq import ZMQServer
from hololinked.server.mqtt import MQTTPublisher
from hololinked.serializers import Serializers
from hololinked.config import global_config
from things import TestThing

import ssl

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

# mqtt_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
# if not os.path.exists("ca.crt"):
#     raise FileNotFoundError("CA certificate 'ca.crt' not found in current directory for MQTT TLS connection")
# mqtt_ssl.load_verify_locations(cafile="ca.crt")
# mqtt_ssl.check_hostname = True
# mqtt_ssl.verify_mode = ssl.CERT_REQUIRED
# mqtt_ssl.minimum_version = ssl.TLSVersion.TLSv1_2

mqtt_publisher = MQTTPublisher(
    hostname="localhost",
    port=8883,
    username="sampleuser",
    password="samplepass",
    qos=1,
    # ssl_context=mqtt_ssl,
)
thing.run(servers=[http_server, zmq_server])
