from .abstractions import ConsumedThingAction, ConsumedThingProperty, ConsumedThingEvent
from ..core.zmq import SyncZMQClient, AsyncZMQClient

class ClientFactory: 
            
    __allowed_attribute_types__ = (ConsumedThingProperty, ConsumedThingAction, ConsumedThingEvent)
    __WRAPPER_ASSIGNMENTS__ =  ('__name__', '__qualname__', '__doc__')

    def get_zmq_client(self):
        sync_zmq_client = SyncZMQClient(id, 
                                        self.identity, 
                                        protocol=protocol, 
                                        logger=self.logger, 
                                        **kwargs
                                    )
       
        async_zmq_client = AsyncZMQClient(id, 
                                        self.identity + '|async', 
                                        client_type=PROXY, 
                                        protocol=protocol, 
                                        zmq_serializer=kwargs.get('serializer', None), handshake=load_thing,
                                        logger=self.logger, 
                                        **kwargs
                                    )
        if load_thing:
            self.load_thing()

    def add_action(self, client: ObjectProxy, action: ConsumedThingAction) -> None:
        # if not func_info.top_owner:
        #     return 
        #     raise RuntimeError("logic error")
        # for dunder in ClientFactory.__WRAPPER_ASSIGNMENTS__:
        #     if dunder == '__qualname__':
        #         info = '{}.{}'.format(client.__class__.__name__, func_info.get_dunder_attr(dunder).split('.')[1])
        #     else:
        #         info = func_info.get_dunder_attr(dunder)
        #     setattr(action, dunder, info)
        setattr(client, action._resource.name, action)

    def add_property(self, client: ObjectProxy, property: ConsumedThingProperty) -> None:
        # if not property_info.top_owner:
        #     return
        #     raise RuntimeError("logic error")
        # for attr in ['__doc__', '__name__']: 
        #     # just to imitate _add_method logic
        #     setattr(property, attr, property_info.get_dunder_attr(attr))
        setattr(client, property._resource.name, property)

    def add_event(client_obj : ObjectProxy, event: ConsumedThingEvent) -> None:
        setattr(client_obj, event._resource.name, event)
    

    def load_thing(self):
        """
        Get exposed resources from server (methods, properties, events) and remember them as attributes of the proxy.
        """
        fetch = ConsumedThingAction(self.zmq_client, CommonRPC.zmq_resource_read(id=self.id), 
                                    invokation_timeout=self._invokation_timeout) # type: ConsumedThingAction
        reply = fetch() # type: typing.Dict[str, typing.Dict[str, typing.Any]]

        for name, data in reply.items():
            if isinstance(data, dict):
                try:
                    if data["what"] == ResourceTypes.EVENT:
                        data = ZMQEvent(**data)
                    elif data["what"] == ResourceTypes.ACTION:
                        data = ZMQAction(**data)
                    else:
                        data = ZMQResource(**data)
                except Exception as ex:
                    ex.add_note("Did you correctly configure your serializer? " + 
                            "This exception occurs when given serializer does not work the same way as server serializer")
                    raise ex from None
            elif not isinstance(data, ZMQResource):
                raise RuntimeError("Logic error - deserialized info about server not instance of hololinked.server.data_classes.ZMQResource")
            if data.what == ResourceTypes.ACTION:
                _add_method(self, ConsumedThingAction(self.zmq_client, data.instruction, self.invokation_timeout, 
                                                self.execution_timeout, data.argument_schema, self.async_zmq_client, self._schema_validator), data)
            elif data.what == ResourceTypes.PROPERTY:
                _add_property(self, ConsumedThingProperty(self.zmq_client, data.instruction, self.invokation_timeout,
                                                self.execution_timeout, self.async_zmq_client), data)
            elif data.what == ResourceTypes.EVENT:
                assert isinstance(data, ZMQEvent)
                event = ConsumedThingEvent(self.zmq_client, data.name, data.obj_name, data.unique_identifier, data.socket_address, 
                            serialization_specific=data.serialization_specific, serializer=self.zmq_client.zmq_serializer, logger=self.logger)
                _add_event(self, event, data)
                self.__dict__[data.name] = event 


from .proxy import ObjectProxy