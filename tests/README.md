# Test Suites

This test suite has both unit and integration tests. They are in a mixed fashion according to requirements defined in each
of the test cases of how a certain feature should behave. It is attempted as much as possible to test from isolated 
parts of the code to the whole system. The following approximate explanation can be given for each of the files:

1. `test_0_utils.py`: Tests for utility functions. These are functions that are used in multiple places in the code and can be used independently.
2. `test_1_message.py`: Tests for the messaging contract of ZMQ, which implements a simple message passing protocol that conveys the exact information required to serve a `Thing` object. For each well standardized protocol, like HTTP, MQTT, etc., we extract the information that is required to run an operation on a `Thing` object, and wrap that information in a ZMQ message. 
3. `test_2_socket.py`: Tests for the socket creation and binding in ZMQ. We allow different types of sockets to be created although `INPROC` is mostly used. 
4. `test_3_serializers.py`: Tests for serializers used to send information on ZMQ socket. 
5. `test_4_thing_init.py`: Tests a `Thing` object whether it can be instantiated. Metaclass, Descriptor registries etc. are also tested here.
6. `test_5_brokers.py`: Tests whether ZMQ request-reply patterns implemented on our simple protocol works as expected.
7. `test_6_rpc_broker.py`: Tests whether the RPC broker, which is built on ZMQ message brokers, works as expected.
8. `test_7_thing_run.py`: Tests whether a `Thing` object can be run using a ZMQ RPC server.
9. `test_8_actions.py`: Tests all possibilities to execute actions of a `Thing` object.
10. `test_9_property.py`: Tests all possibilities to execute properties of a `Thing` object.
11. `test_10_events.py`: Tests all possibilities to execute events of a `Thing` object.
 
The tests are written with `unittest` framework.  

### Running the tests

To run the tests, just do: 

```bash
python -m unittest
```

### More Documentation

In each test file, there are more detailed explanations of the tests. 

To document a test
1. Create a class and subclass from `TestCase` which is in `utils.py` (in this folder). 
2. State all the tests the class will perform
3. Within each test method, state the purpose of the test as docstring
4. Then, state each requirement one by one within a comment ("# req 1.") and test them. 
