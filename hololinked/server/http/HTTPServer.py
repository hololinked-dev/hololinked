
self._lost_things = dict() # see update_router_with_thing
self._zmq_protocol = ZMQ_TRANSPORTS.IPC
self._zmq_inproc_socket_context = None 
self._zmq_inproc_event_context = None
self._local_rules = dict() # type: typing.Dict[str, typing.List[InteractionAffordance]]
self._checked = False
 
