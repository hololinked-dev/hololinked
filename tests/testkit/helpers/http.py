import sys
import time

import requests


hostname_prefix = "http://127.0.0.1"
readiness_endpoint = "/readiness"
liveness_endpoint = "/liveness"
stop_endpoint = "/stop"
start_acquisition_endpoint = "/start-acquisition"
intensity_measurement_event_endpoint = "/intensity-measurement-event"
stop_acquisition_endpoint = "/stop-acquisition"


def wait_until_server_ready(port: int, tries: int = 10) -> None:
    session = requests.Session()
    for _ in range(tries):
        try:
            response = session.get(f"{hostname_prefix}:{port}{liveness_endpoint}")
            if response.status_code in [200, 201, 202, 204]:
                response = session.get(f"{hostname_prefix}:{port}{readiness_endpoint}")
                if response.status_code in [200, 201, 202, 204]:
                    return
        except Exception as ex:
            print(f"received exception while checking server readiness, retrying - {ex}")
            pass
        time.sleep(1)
    print(f"Server on port {port} not ready after {tries} tries, you need to retrigger this test job")
    sys.exit(1)


def sse_stream(url: str, chunk_size: int = 2048, **kwargs):
    with requests.get(url, stream=True, **kwargs) as resp:
        resp.raise_for_status()
        buffer = ""  # type: str
        for chunk in resp.iter_content(chunk_size=chunk_size, decode_unicode=True):
            buffer += chunk
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                event = {}
                for line in raw_event.splitlines():
                    if not line or line.startswith(":"):
                        continue
                    if ":" in line:
                        field, value = line.split(":", 1)
                        event.setdefault(field, "")
                        event[field] += value.lstrip()
                yield event
