# run_testthing_basic.py
import logging, time, uuid
from tests.things.test_thing import TestThing
from hololinked.server.security import BcryptBasicSecurity

thing_id = f"tt-{uuid.uuid4().hex[:6]}"
port = 60110
sec = BcryptBasicSecurity(username="cliuser", password="clipass")

thing = TestThing(id=thing_id, log_level=logging.INFO)
thing.run_with_http_server(
    forked=True, port=port, config={"allow_cors": True}, security_schemes=[sec]
)

print(f"TD: http://127.0.0.1:{port}/{thing_id}/resources/wot-td")
print(f"Prop: http://127.0.0.1:{port}/{thing_id}/base-property")
while True: time.sleep(5)
