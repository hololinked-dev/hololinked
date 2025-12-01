# hololinked - Pythonic Object-Oriented Supervisory Control & Data Acquisition / Internet of Things

## Description

`hololinked` is a beginner-friendly, extensible pythonic tool suited for instrumentation control and data acquisition over network (IoT & SCADA).

As a novice, you have a requirement to control and capture data from your hardware, say in your electronics or science lab, and you want to show the data in a dashboard, provide a PyQt GUI or run automated scripts, `hololinked` can help. Even for isolated desktop applications or a small setup without networking, one can still separate the concerns of the tools that interact with the hardware & the hardware itself.

If you are a web developer or an industry professional looking for a web standards compatible (high-speed) IoT runtime, `hololinked` can be a decent choice. By conforming to [W3C Web of Things](https://www.w3.org/WoT/), one can expect a consistent API and flexible bidirectional message flow to interact with your devices, irrespective of the underlying protocol. Currently HTTP, MQTT & ZMQ are supported. See [Use Cases Table](https://docs.hololinked.dev/introduction/use-cases).

This implementation is based on RPC, built ground-up in python keeping both the latest web technologies and python principles in mind.

[![CI Pipeline](https://github.com/hololinked-dev/hololinked/actions/workflows/ci-pipeline.yml/badge.svg)](https://github.com/hololinked-dev/hololinked/actions/workflows/ci-pipeline.yml) [![Documentation Status](https://img.shields.io/github/actions/workflow/status/hololinked-dev/docs/ci.yaml?label=Build%20And%20Publish%20Docs)](https://github.com/hololinked-dev/docs) [![SAST](https://img.shields.io/badge/sast%20reports-bandit-yellow.svg)](https://docs.hololinked.dev/introduction/security-scanning) ![Ruff](https://img.shields.io/badge/linter-ruff-blue?logo=ruff&logoColor=white) [![PyPI](https://img.shields.io/pypi/v/hololinked?label=pypi%20package)](https://pypi.org/project/hololinked/) [![Anaconda](https://anaconda.org/conda-forge/hololinked/badges/version.svg)](https://anaconda.org/conda-forge/hololinked) [![codecov](https://codecov.io/github/hololinked-dev/hololinked/graph/badge.svg?token=5DI4XJ2KX9)](https://codecov.io/github/hololinked-dev/hololinked) [![Conda Downloads](https://img.shields.io/conda/d/conda-forge/hololinked)](https://anaconda.org/conda-forge/hololinked) [![PyPI - Downloads](https://img.shields.io/pypi/dm/hololinked?label=pypi%20downloads)](https://pypistats.org/packages/hololinked) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.15155942.svg)](https://doi.org/10.5281/zenodo.12802841) [![Discord](https://img.shields.io/discord/1265289049783140464?label=Discord%20Members&logo=discord)](https://discord.com/invite/kEz87zqQXh) [![email](https://img.shields.io/badge/email-brown)](mailto:info@hololinked.dev) [![Feedback Form](https://img.shields.io/badge/feedback%20form-red)](https://forms.gle/FB4XwkUDt1wV4GGPA)

## To Install

From pip - `pip install hololinked` <br>
From conda - <br>
`pip install aiomqtt` (needs to be installed separately) <br>
`conda install -c conda-forge hololinked` <br>

Or, clone the repository (main branch for latest codebase, which can also contain bugs) and install `pip install .` / `pip install -e .`. The [uv environment `uv.lock`](#setup-development-environment) can also help to setup all dependencies. Currently the dependencies are hard pinned to promote stability, therefore consider using a virtual environment.

## Usage/Quickstart

Each device or thing can be controlled systematically when their design in software is segregated into properties, actions and events. In object oriented terms:

- the hardware is represented by a class
- properties are validated get-set attributes of the class which may be used to model settings, hold captured/computed data or generic network accessible quantities
- actions are methods which issue commands like connect/disconnect, execute a control routine, start/stop measurement, or run arbitrary python logic
- events can asynchronously communicate/push arbitrary data to a client, like alarm messages, streaming measured quantities etc.

For example, consider an optical spectrometer, the following code is possible:

### Import Statements

```python
from hololinked.core import Thing, Property, action, Event # interactions with hardware
from hololinked.core.properties import String, Integer, Number, List # some property types
from seabreeze.spectrometers import Spectrometer # a device driver
```

### Definition of one's own Hardware Controlling Class

subclass from `Thing` class to make a "network accessible Thing":

```python
class OceanOpticsSpectrometer(Thing):
    """
    OceanOptics spectrometers using seabreeze library. Device is identified by serial number.
    """
```

### Instantiating Properties

Say, we wish to make device serial number, integration time and the captured intensity as properties. There are certain predefined properties available like `String`, `Number`, `Boolean` etc. or one may define one's own using [pydantic or JSON schema](https://docs.hololinked.dev/howto/articles/properties/#schema-constrained-property). To create properties:

```python
class OceanOpticsSpectrometer(Thing):
    """class doc"""

    serial_number = String(default=None, allow_None=True,
                        doc="serial number of the spectrometer to connect/or connected")

    integration_time = Number(default=1000, bounds=(0.001, None), crop_to_bounds=True,
                        doc="integration time of measurement in milliseconds")

    intensity = List(default=None, allow_None=True, doc="captured intensity", readonly=True,
                        fget=lambda self: self._intensity)

    def __init__(self, id, serial_number, **kwargs):
        super().__init__(id=id, serial_number=serial_number, **kwargs)
```

In non-expert terms, properties look like class attributes however their data containers are instantiated at object instance level by default. This is possible due to [python descriptor protocol](https://realpython.com/python-descriptors/). For example, the `integration_time` property defined above as `Number`, whenever set/written, will be validated as a float or int, cropped to bounds and assigned as an attribute to each **instance** of the `OceanOpticsSpectrometer` class with an internally generated name. It is not necessary to know this internally generated name as the property value can be accessed again in any python logic using the dot operator, say, `print(self.integration_time)`.

One may overload the get-set (or read-write) of properties to customize their behavior:

```python
class OceanOpticsSpectrometer(Thing):

    integration_time = Number(default=1000, bounds=(0.001, None), crop_to_bounds=True,
                            doc="integration time of measurement in milliseconds")

    @integration_time.setter
    def set_integration_time(self, value : float):
        self.device.write_integration_time_micros(int(value*1000))
        # seabreeze does not provide a write_integration_time_micros method,
        # this is only an example

    @integration_time.getter
    def get_integration_time(self) -> float:
        try:
            return self.device.read_integration_time_micros() / 1000
            # seabreeze does not provide a read_integration_time_micros method,
            # this is only an example
        except AttributeError:
            return self.properties["integration_time"].default

```

In this case, instead of generating a data container with an internal name, the setter method is called when `integration_time` property is set/written. One might add the hardware device driver logic here (say, supplied by the manufacturer) or a protocol that applies the property directly onto the device. One would also want the getter to read from the device directly as well.

Those familiar with Web of Things (WoT) terminology may note that these properties generate the property affordance. An example for `integration_time` is as follows:

```JSON
"integration_time": {
    "title": "integration_time",
    "description": "integration time of measurement in milliseconds",
    "type": "number",
    "forms": [{
            "href": "https://example.com/spectrometer/integration-time",
            "op": "readproperty",
            "htv:methodName": "GET",
            "contentType": "application/json"
        },{
            "href": "https://example.com/spectrometer/integration-time",
            "op": "writeproperty",
            "htv:methodName": "PUT",
            "contentType": "application/json"
        }
    ],
    "minimum": 0.001
},
```

If you are **not familiar** with Web of Things or the term "property affordance", consider the above JSON as a description of
what the property represents and how to interact with it from somewhere else (in this case, over HTTP). Such a JSON is both human-readable, yet consumable by any application that may use the property - say, a client provider to create a client object to interact with the property or a GUI application to autogenerate a suitable input field for this property.

[![Property Documentation](https://img.shields.io/badge/Property%20Docs-Read%20More-blue?logo=readthedocs)](https://docs.hololinked.dev/beginners-guide/articles/properties/) [![Try it Out](https://img.shields.io/badge/Try%20it%20Out-Live%20Demo-brightgreen?logo=python)](https://control-panel.hololinked.dev/#https://examples.hololinked.dev/simulations/oscilloscope/resources/wot-td)

### Specify Methods as Actions

decorate with `action` decorator on a python method to claim it as a network accessible method:

```python

class OceanOpticsSpectrometer(Thing):

    @action(input_schema={"type": "object", "properties": {"serial_number": {"type": "string"}}})
    def connect(self, serial_number = None):
        """connect to spectrometer with given serial number"""
        if serial_number is not None:
            self.serial_number = serial_number
        self.device = Spectrometer.from_serial_number(self.serial_number)
        self._wavelengths = self.device.wavelengths().tolist()

    @action()
    def disconnect(self):
        """disconnect from the spectrometer"""
        self.device.close()
```

Methods that are neither decorated with action decorator nor acting as getters-setters of properties remain as plain python methods and are **not** accessible on the network.

In WoT Terminology, again, such a method becomes specified as an action affordance (or a description of what the action represents and how to interact with it):

```JSON
"connect": {
    "title": "connect",
    "description": "connect to spectrometer with given serial number",
    "forms": [
        {
            "href": "https://example.com/spectrometer/connect",
            "op": "invokeaction",
            "htv:methodName": "POST",
            "contentType": "application/json"
        }
    ],
    "input": {
        "type": "object",
        "properties": {
            "serial_number": {
                "type": "string"
            }
        },
        "additionalProperties": false
    }
},
```

> input and output schema ("input" field above which describes the argument type `serial_number`) are optional and are discussed in docs

[![Actions Documentation](https://img.shields.io/badge/Actions%20Docs-Read%20More-blue?logo=readthedocs)](https://docs.hololinked.dev/beginners-guide/articles/actions/) [![Try it Out](https://img.shields.io/badge/Try%20it%20Out-Live%20Demo-brightgreen?logo=python)](https://control-panel.hololinked.dev/#https://examples.hololinked.dev/simulations/oscilloscope/resources/wot-td)

### Defining and Pushing Events

create a named event using `Event` object that can push any arbitrary serializable data:

```python
class OceanOpticsSpectrometer(Thing):

    intensity_measurement_event = Event(name='intensity-measurement-event',
            doc="""event generated on measurement of intensity,
            max 30 per second even if measurement is faster.""",
            schema=intensity_event_schema)
            # schema is optional and will be discussed in documentation,
            # assume the intensity_event_schema variable is valid

    def capture(self): # not an action, but a plain python method
        self._run = True
        last_time = time.time()
        while self._run:
            self._intensity = self.device.intensities(
                                        correct_dark_counts=False,
                                        correct_nonlinearity=False
                                    )
            curtime = datetime.datetime.now()
            measurement_timestamp = curtime.strftime('%d.%m.%Y %H:%M:%S.') + '{:03d}'.format(
                                                            int(curtime.microsecond /1000))
            if time.time() - last_time > 0.033: # restrict speed to avoid overloading
                self.intensity_measurement_event.push({
                    "timestamp" : measurement_timestamp,
                    "value" : self._intensity.tolist()
                })
                last_time = time.time()

    @action()
    def start_acquisition(self):
        if self._acquisition_thread is not None and self._acquisition_thread.is_alive():
            return
        self._acquisition_thread = threading.Thread(target=self.capture)
        self._acquisition_thread.start()

    @action()
    def stop_acquisition(self):
        self._run = False
```

Events can stream live data without polling or push data to a client whose generation in time is uncontrollable.

In WoT Terminology, such an event becomes specified as an event affordance (or a description of
what the event represents and how to subscribe to it) with subprotocol SSE:

```JSON
"intensity_measurement_event": {
    "title": "intensity-measurement-event",
    "description": "event generated on measurement of intensity, max 30 per second even if measurement is faster.",
    "forms": [
        {
          "href": "https://example.com/spectrometer/intensity/measurement-event",
          "subprotocol": "sse",
          "op": "subscribeevent",
          "htv:methodName": "GET",
          "contentType": "text/plain"
        }
    ],
    "data": {
        "type": "object",
        "properties": {
            "value": {
                "type": "array",
                "items": {
                    "type": "number"
                }
            },
            "timestamp": {
                "type": "string"
            }
        }
    }
}
```

> data schema ("data" field above which describes the event payload) are optional and discussed in documentation

Events follow a pub-sub model with '1 publisher to N subscribers' per `Event` object, both through any supported protocol including HTTP server sent events.

[![Events Documentation](https://img.shields.io/badge/Events%20Docs-Read%20More-blue?logo=readthedocs)](https://docs.hololinked.dev/beginners-guide/articles/events/) [![Try it Out](https://img.shields.io/badge/Try%20it%20Out-Live%20Demo-brightgreen?logo=python)](https://control-panel.hololinked.dev/#https://examples.hololinked.dev/simulations/oscilloscope/resources/wot-td)

### Start with a Protocol Server

One can start the Thing object with one or more protocols simultaneously. Currently HTTP & ZMQ is supported. With HTTP server:

```python
import ssl, os, logging

if __name__ == '__main__':
    ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(f'assets{os.sep}security{os.sep}certificate.pem',
                        keyfile = f'assets{os.sep}security{os.sep}key.pem')
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3

    OceanOpticsSpectrometer(
        id='spectrometer',
        serial_number='S14155',
        log_level=logging.DEBUG
    ).run_with_http_server(
        port=9000, ssl_context=ssl_context
    )
```

The base URL is constructed as `http(s)://<hostname>:<port>/<thing_id>`

With ZMQ:

```python

if __name__ == '__main__':
    OceanOpticsSpectrometer(
        id='spectrometer',
        serial_number='S14155',
    ).run(
        access_points=['IPC', 'tcp://*:9999']
    )
    # both interprocess communication & TCP
```

Multiple:

```python

if __name__ == '__main__':
    OceanOpticsSpectrometer(
        id='spectrometer',
        serial_number='S14155',
    ).run(
       access_points=[
            ("ZMQ", "IPC"),
            ("HTTP", 8080),
        ]
    )
    # HTTP & ZMQ Interprocess Communication
```

[![Resources to Get Started](https://img.shields.io/badge/Resources-Get%20Started-orange?logo=book)](#resources)

## Client Side Applications

To compose client objects, the JSON description of the properties, actions and events are used, which are summarized into a [Thing Description](https://www.w3.org/TR/wot-thing-description11). These descriptions are autogenerated, so at least in the beginner stages, you dont need to know how they work. The following code would be possible:

### Python Clients

Import the `ClientFactory` and create an instance of the client for the desired protocol:

```python
from hololinked.client import ClientFactory

# for HTTP
thing = ClientFactory.http(url="http://localhost:8000/spectrometer/resources/wot-td")
# For HTTP, one needs to append `/resource/wot-td` to the base URL to construct the full URL as `http(s)://<hostname>:<port>/<thing_id>/resources/wot-td`. At this endpoint, the Thing Description will be autogenerated and loaded to compose a client.

# zmq IPC
thing = ClientFactory.zmq(thing_id='spectrometer', access_point='IPC')
# zmq TCP
thing = ClientFactory.zmq(thing_id='spectrometer', access_point='tcp://localhost:9999')
# For ZMQ, Thing Description loading is automatically mediated simply by specifying how to access the Thing
```

To issue operations:

<details open>
<summary>Read Property</summary>

```python
thing.read_property("integration_time")
# or use dot operator
thing.integration_time
```

within an async function:

```python
async def func():
    await thing.async_read_property("integration_time")
    # dot operator not supported
```

</details>

<details open> 
<summary>Write Property</summary>

```python
thing.write_property("integration_time", 2000)
# or use dot operator
thing.integration_time = 2000
```

within an async function:

```python
async def func():
    await thing.async_write_property("integration_time", 2000)
    # dot operator not supported
```

<details open> 
<summary>Invoke Action</summary>

```python
thing.invoke_action("connect", serial_number="S14155")
# or use dot operator
thing.connect(serial_number="S14155")
```

within an async function:

```python
async def func():
    await thing.async_invoke_action("connect", serial_number="S14155")
    # dot operator not supported
```

</details>

<details open>
<summary>Subscribe to Event</summary>

```python

thing.subscribe_event("intensity_measurement_event", callbacks=lambda value: print(value))
```

There is no async subscribe, as events by nature appear at arbitrary times only when pushed by the server. Yet, events can be asynchronously listened and callbacks can be asynchronously invoked. Please refer documentation. To unsubscribe:

```python
thing.unsubscribe_event("intensity_measurement_event")
```

</details>

<details open>
<summary>Observe Property</summary>

```python

thing.observe_property("integration_time", callbacks=lambda value: print(value))
```

Only observable properties (property where `observable` was set to `True`) can be observed. To unobserve:

```python
thing.unobserve_property("integration_time")
```

</details>

Operations which rely on request-reply pattern (properties and actions) also support one-way and no-block calls:

- `oneway` - issue the operation and dont collect the reply
- `noblock` - issue the operation, obtain a message ID and collect the reply when you want

[![Python Client Docs](https://img.shields.io/badge/Python%20Client%20Docs-Read%20More-blue?logo=readthedocs)](https://docs.hololinked.dev/beginners-guide/articles/object-proxy/)

### Javascript Clients

Similary, one could consume the Thing Description in a Node.js script using Eclipse [ThingWeb node-wot](https://github.com/eclipse-thingweb/node-wot):

```js
const { Servient } = require("@node-wot/core");
const HttpClientFactory = require("@node-wot/binding-http").HttpClientFactory;

const servient = new Servient();
servient.addClientFactory(new HttpClientFactory());

servient.start().then((WoT) => {
    fetch("http://localhost:8000/spectrometer/resources/wot-td")
        .then((res) => res.json())
        .then((td) => WoT.consume(td))
        .then((thing) => {
        thing.readProperty("integration_time").then(async(interactionOutput) => {
            console.log("Integration Time: ", await interactionOutput.value());
        })
)});
```

If you're using HTTPS, just make sure the server certificate is valid or trusted by the client.

```js
const HttpsClientFactory = require("@node-wot/binding-http").HttpsClientFactory;
servient.addClientFactory(new HttpsClientFactory({ allowSelfSigned: true }));
```

(example [here](https://gitlab.com/hololinked/examples/clients/node-clients/phymotion-controllers-app/-/blob/main/src/App.tsx?ref_type=heads#L77))

To issue operations:

<details open>
<summary>Read Property</summary>

`thing.readProperty("integration_time").then(async(interactionOutput) => {
  console.log("Integration Time:", await interactionOutput.value());
});`

</details>
<details open> 
<summary>Write Property</summary>

`thing.writeProperty("integration_time", 2000).then(() => {
  console.log("Integration Time updated");
});`

</details>
<details open>
<summary>Invoke Action</summary>

`thing.invokeAction("connect", { serial_number: "S14155" }).then(() => {
  console.log("Device connected");
});`

</details>
<details open>
<summary>Subscribe to Event</summary>

`thing.subscribeEvent("intensity_measurement_event", async (interactionOutput) => {
  console.log("Received event:", await interactionOutput.value());
});`

</details>

<details open>
<summary>Observe Property</summary>

`thing.observeProperty("integration_time", async (interactionOutput) => {
    console.log("Observed integration_time:", await interactionOutput.value());
});`

</details>

<details>
<summary>Links to React Examples</summary>
In React, the Thing Description may be fetched inside `useEffect` hook, the client passed via a `useContext` hook (or a global state manager). The individual operations can be performed in their own callbacks attached to DOM elements:

- [fetch TD](https://gitlab.com/hololinked/examples/clients/node-clients/phymotion-controllers-app/-/blob/main/src/App.tsx?ref_type=heads#L96)
- [issue operations](https://gitlab.com/hololinked/examples/clients/node-clients/phymotion-controllers-app/-/blob/main/src/components/movements.tsx?ref_type=heads#L54)
</details>

<br>

[![node-wot docs](https://img.shields.io/badge/nodewot%20docs-Read%20More-blue?logo=JavaScript)](https://thingweb.io/docs/node-wot/API)

## Resources

- [examples repository](https://github.com/hololinked-dev/examples) - detailed examples for both clients and servers
- [infrastructure components](https://github.com/hololinked-dev/daq-system-infrastructure) - docker compose files to setup postgres or mongo databases with admin interfaces, Identity and Access Management system among other components.
- [helper GUI](https://github.com/hololinked-dev/thing-control-panel) - view & interact with your object's actions, properties and events.
- [live demo](https://control-panel.hololinked.dev/#https://examples.hololinked.dev/simulations/oscilloscope/resources/wot-td) - an example of an oscilloscope available for live test

> You may use a script deployment/automation tool to remote stop and start servers, in an attempt to remotely control your hardware scripts.

## Contributing

See [organization info](https://github.com/hololinked-dev) for details regarding contributing to this package. There are:

- [good first issues](https://github.com/hololinked-dev/hololinked/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)
- [setup development environment](https://docs.hololinked.dev/introduction/contributing#setup-development-environment)
- [discord group](https://discord.com/invite/kEz87zqQXh)
- [weekly meetings](https://github.com/hololinked-dev/#monthly-meetings) and
- [project planning](https://github.com/orgs/hololinked-dev/projects/4) to discuss activities around this repository.

## Currently Supported Features

Some other features that are currently supported:

- use a custom finite state machine.
- database (Postgres, MySQL, SQLite - based on SQLAlchemy) support for storing and loading properties when the object dies and restarts.
- auto-generate Thing Description for Web of Things applications.
- use serializer of your choice (except for HTTP) - MessagePack, JSON, pickle etc. & extend serialization to suit your requirement
- asyncio event loops on server side
