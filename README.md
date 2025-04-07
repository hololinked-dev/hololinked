# hololinked - Pythonic Object-Oriented Supervisory Control & Data Acquisition / Internet of Things

### Description

`hololinked` is a beginner-friendly server side pythonic tool suited for instrumentation control and data acquisition over network, especially with HTTP. If you have a requirement to control and capture data from your hardware/instrumentation, show the data in a browser/dashboard, provide a GUI or run automated scripts, `hololinked` can help. Even for isolated applications or a small lab setup without networking concepts, one can still separate the concerns of the tools that interact with the hardware & the hardware itself.

For those that understand, this package is a ZMQ/HTTP-RPC.
 
[![Documentation Status](https://readthedocs.org/projects/hololinked/badge/?version=latest)](https://hololinked.readthedocs.io/en/latest/?badge=latest) [![PyPI](https://img.shields.io/pypi/v/hololinked?label=pypi%20package)](https://pypi.org/project/hololinked/) [![Anaconda](https://anaconda.org/conda-forge/hololinked/badges/version.svg)](https://anaconda.org/conda-forge/hololinked)
[![codecov](https://codecov.io/gh/VigneshVSV/hololinked/graph/badge.svg?token=JF1928KTFE)](https://codecov.io/gh/VigneshVSV/hololinked) 
<br>
[![email](https://img.shields.io/badge/email%20me-brown)](mailto:vignesh.vaidyanathan@hololinked.dev) [![ways to contact me](https://img.shields.io/badge/ways_to_contact_me-brown)](https://hololinked.dev/contact)
<br>
[![PyPI - Downloads](https://img.shields.io/pypi/dm/hololinked?label=pypi%20downloads)](https://pypistats.org/packages/hololinked)
[![Conda Downloads](https://img.shields.io/conda/d/conda-forge/hololinked)](https://anaconda.org/conda-forge/hololinked)

### To Install

From pip - ``pip install hololinked`` <br>
From conda -  `conda install -c conda-forge hololinked`

Or, clone the repository (main branch for latest codebase) and install `pip install .` / `pip install -e .`. The conda env ``hololinked.yml`` can also help to setup all dependencies. 

### Usage/Quickstart

`hololinked` is compatible with the [Web of Things](https://www.w3.org/WoT/) recommended pattern for developing hardware/instrumentation control software. 
Each device or thing can be controlled systematically when their design in software is segregated into properties, actions and events. In object oriented terms:
- the hardware is (generally) represented by a class 
- properties are validated get-set attributes of the class which may be used to model settings, hold captured/computed data or generic network accessible quantities
- actions are methods which issue commands like connect/disconnect, execute a control routine, start/stop measurement, or run arbitray python logic
- events can asynchronously communicate/push arbitrary data to a client, like alarm messages, streaming measured quantities etc.

In this package, the base class which enables this classification is the `Thing` class. Any class that inherits the `Thing` class 
can instantiate properties, actions and events which become visible to a client in this segragated manner. For example, consider an optical spectrometer, the following code is possible:

> This is a fairly mid-level intro focussed on HTTP. If you are beginner or looking for ZMQ which can be used with no networking knowledge, check [How-To](https://hololinked.readthedocs.io/en/latest/howto/index.html)

#### Import Statements

```python

from hololinked.server import Thing, Property, action, Event
from hololinked.server.properties import String, Integer, Number, List
from seabreeze.spectrometers import Spectrometer # device driver
```

#### Definition of one's own hardware controlling class

subclass from Thing class to "make a network accessible Thing":

```python 
class OceanOpticsSpectrometer(Thing):
    """
    OceanOptics spectrometers using seabreeze library. Device is identified by serial number. 
    """
    
```

#### Instantiating properties

Say, we wish to make device serial number, integration time and the captured intensity as properties. There are certain predefined properties available like `String`, `Number`, `Boolean` etc. 
or one may define one's own. To create properties:

```python

class OceanOpticsSpectrometer(Thing):
    """class doc"""
    
    serial_number = String(default=None, allow_None=True, URL_path='/serial-number', 
                        doc="serial number of the spectrometer to connect/or connected",
                        http_method=("GET", "PUT"))
    # GET and PUT is default for reading and writing the property respectively.
    # So you can leave it out, especially if you are going to use ZMQ and dont understand HTTP

    integration_time = Number(default=1000, bounds=(0.001, None), crop_to_bounds=True, 
                            URL_path='/integration-time', 
                            doc="integration time of measurement in milliseconds")

    intensity = List(default=None, allow_None=True, 
                    doc="captured intensity", readonly=True, 
                    fget=lambda self: self._intensity)     

    def __init__(self, instance_name, serial_number, **kwargs):
        super().__init__(instance_name=instance_name, serial_number=serial_number, **kwargs)

```
> There is an ongoing work to remove HTTP API from the property API and completely move them to the HTTP server

In non-expert terms, properties look like class attributes however their data containers are instantiated at object instance level by default.
For example, the `integration_time` property defined above as `Number`, whenever set/written, will be validated as a float or int, cropped to bounds and assigned as an attribute to each instance of the `OceanOpticsSpectrometer` class with an internally generated name. It is not necessary to know this internally generated name as the property value can be accessed again in any python logic, say, `print(self.integration_time)`. 

To overload the get-set (or read-write) of properties, one may do the following:
```python
class OceanOpticsSpectrometer(Thing):

    integration_time = Number(default=1000, bounds=(0.001, None), crop_to_bounds=True, 
                            URL_path='/integration-time', 
                            doc="integration time of measurement in milliseconds")

    @integration_time.setter # by default called on http PUT method
    def apply_integration_time(self, value : float):
        self.device.integration_time_micros(int(value*1000))
        self._integration_time = int(value) 
      
    @integration_time.getter # by default called on http GET method
    def get_integration_time(self) -> float:
        try:
            return self._integration_time
        except AttributeError:
            return self.properties["integration_time"].default 

```

In this case, instead of generating a data container with an internal name, the setter method is called when `integration_time` property is set/written. One might add the hardware device driver logic here (say, supplied by the manufacturer) or a protocol that talks directly to the device to apply the property onto the device. In the above example, there is not a way provided by the device driver library to read the value from the device, so we store it in a variable after applying it and supply the variable back to the getter method. Normally, one would also want the getter to read from the device directly.
 
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
If you are <span style="text-decoration: underline">not familiar</span> with Web of Things or the term "property affordance", consider the above JSON as a description of 
what the property represents and how to interact with it from somewhere else. Such a JSON is both human-readable, yet consumable by any application that may use the property - say, a client provider to create a client object to interact with the property or a GUI application to autogenerate a suitable input field for this property. 
For example, the Eclipse ThingWeb [node-wot](https://github.com/eclipse-thingweb/node-wot) supports this feature to produce a HTTP(s) client that can issue `readProperty("integration_time")` and `writeProperty("integration_time", 1000)` to read and write this property.

The URL path segment `../spectrometer/..` in href field is taken from the `instance_name` which was specified in the `__init__`. 
This is a mandatory key word argument to the parent class `Thing` to generate a unique name/id for the instance. One should use URI compatible strings.

#### Specify methods as actions

decorate with `action` decorator on a python method to claim it as a network accessible method:

```python

class OceanOpticsSpectrometer(Thing):

    @action(URL_path='/connect', http_method="POST") # POST is default for actions
    def connect(self, serial_number = None):
        """connect to spectrometer with given serial number"""
        if serial_number is not None:
            self.serial_number = serial_number
        self.device = Spectrometer.from_serial_number(self.serial_number)
        self._wavelengths = self.device.wavelengths().tolist()

    # So you can leave it out, especially if you are going to use ZMQ and dont understand HTTP
    @action()
    def disconnect(self):
        """disconnect from the spectrometer"""
        self.device.close()
 
```

Methods that are neither decorated with action decorator nor acting as getters-setters of properties remain as plain python methods and are **not** accessible on the network.

In WoT Terminology, again, such a method becomes specified as an action affordance (or a description of what the action represents
and how to interact with it):

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
> input and output schema ("input" field above which describes the argument type `serial_number`) are optional and will be discussed in docs

#### Defining and pushing events

create a named event using `Event` object that can push any arbitrary data:

```python
class OceanOpticsSpectrometer(Thing):

    # only GET HTTP method possible for events
    intensity_measurement_event = Event(name='intensity-measurement-event', 
            URL_path='/intensity/measurement-event',
            doc="""event generated on measurement of intensity, 
            max 30 per second even if measurement is faster.""",
            schema=intensity_event_schema) 
            # schema is optional and will be discussed later,
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

    @action(URL_path='/acquisition/start', http_method="POST")
    def start_acquisition(self):
        if self._acquisition_thread is not None and self._acquisition_thread.is_alive():
            return
        self._acquisition_thread = threading.Thread(target=self.capture) 
        self._acquisition_thread.start()

    @action(URL_path='/acquisition/stop', http_method="POST")
    def stop_acquisition(self):
        self._run = False 
```
Events can stream live data without polling or push data to a client whose generation in time is uncontrollable. 

In WoT Terminology, such an event becomes specified as an event affordance (or a description of 
what the event represents and how to subscribe to it) with subprotocol SSE (HTTP-SSE):

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
> data schema ("data" field above which describes the event payload) are optional and discussed later

Events follow a pub-sub model with '1 publisher to N subscribers' per `Event` object, both through ZMQ and HTTP SSE. 

To start the Thing, a configurable HTTP Server is already available (from `hololinked.server.HTTPServer`) which redirects HTTP requests to the object:

```python
import ssl, os, logging
from multiprocessing import Process
from hololinked.server import HTTPServer

if __name__ == '__main__':
    ssl_context = ssl.SSLContext(protocol = ssl.PROTOCOL_TLS)
    ssl_context.load_cert_chain(f'assets{os.sep}security{os.sep}certificate.pem',
                        keyfile = f'assets{os.sep}security{os.sep}key.pem')
    
    O = OceanOpticsSpectrometer(
        instance_name='spectrometer',
        serial_number='S14155',
        log_level=logging.DEBUG
    )
    O.run_with_http_server(ssl_context=ssl_context)
    # or O.run(zmq_protocols='IPC') - interprocess communication and no HTTP
    # or O.run(zmq_protocols=['IPC', 'TCP'], tcp_socket_address='tcp://*:9999')
    # both interprocess communication & TCP, no HTTP 
```
> There is an ongoing work to remove HTTP API from the API of all of properties, actions and events and completely move them to the HTTP server for a more accurate syntax. The functionality will not change though.

Here one can see the use of `instance_name` and why it turns up in the URL path. See the detailed example of the above code [here](https://gitlab.com/hololinked-examples/oceanoptics-spectrometer/-/blob/simple/oceanoptics_spectrometer/device.py?ref_type=heads). 

##### NOTE - The package is under active development. Contributors welcome, please check CONTRIBUTING.md and the open issues. Some issues can also be independently dealt without much knowledge of this package.  

- [examples repository](https://github.com/hololinked-dev/examples) - detailed examples for both clients and servers
- [helper GUI](https://github.com/hololinked-dev/thing-control-panel) - view & interact with your object's actions, properties and events. 
- [live demo](https://control-panel.hololinked.dev/#https://examples.hololinked.dev/simulations/oscilloscope/resources/wot-td) - an example of an oscilloscope available for live test
 
See a list of currently supported possibilities while using this package [below](#currently-supported). 

> You may use a script deployment/automation tool to remote stop and start servers, in an attempt to remotely control your hardware scripts. 

### A little more about Usage

The HTTP API may be autogenerated or adjusted by the user. If your plan is to develop a truly networked system, it is recommended to learn more and 
use [Thing Descriptions](https://www.w3.org/TR/wot-thing-description11) to describe your hardware (This is optional and one can still use a classic HTTP client). A Thing Description will be automatically generated if absent as shown in JSON examples above or can be supplied manually. The default end point to fetch thing descriptions are: <br> `http(s)://<host name>/<instance name of the thing>/resources/wot-td` <br>
If there are errors in generation of Thing Description
(mostly due to JSON non-complaint types), one could use: <br> `http(s)://<host name>/<instance name of the thing>/resources/wot-td?ignore_errors=true`

(client docs will be updated here next, also check official docs)

### Currently Supported

- control method execution and property write with a custom finite state machine.
- database (Postgres, MySQL, SQLite - based on SQLAlchemy) support for storing and loading properties when the object dies and restarts. 
- auto-generate Thing Description for Web of Things applications. 
- use serializer of your choice (except for HTTP) - MessagePack, JSON, pickle etc. & extend serialization to suit your requirement. HTTP Server will support only JSON serializer to maintain comptibility with Javascript (MessagePack may be added later). Default is JSON serializer based on msgspec.
- asyncio compatible - async RPC server event-loop and async HTTP Server - write methods in async 
- choose from multiple ZeroMQ transport methods which offers some possibilities like the following without changing the code:
  - expose only a dashboard or web page on the network without exposing the hardware itself
  - run direct ZMQ-TCP server without HTTP details
  - serve multiple objects with the same HTTP server, run HTTP Server & python object in separate processes or the same process
 
Again, please check examples or the code for explanations. Documentation is being activety improved. 

### Contributing

See [organization info](https://github.com/hololinked-dev) for details regarding contributing to this package. There is:
- discord group - [![Discord](https://img.shields.io/discord/1265289049783140464?label=Discord%20Members&logo=discord)](https://discord.com/invite/kEz87zqQXh) 
- [weekly meetings](https://github.com/hololinked-dev/#monthly-meetings) and 
- [project planning](https://github.com/orgs/hololinked-dev/projects/4)  to discuss activities around this repository. 