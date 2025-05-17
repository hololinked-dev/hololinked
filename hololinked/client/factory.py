import uuid

from .abstractions import ConsumedThingAction, ConsumedThingProperty, ConsumedThingEvent
from .zmq.consumed_interactions import ZMQAction, ZMQEvent, ZMQProperty
from ..core.zmq import SyncZMQClient, AsyncZMQClient
from ..core import Thing, Action
from ..td.interaction_affordance import PropertyAffordance, ActionAffordance, EventAffordance



class ClientFactory: 
            
    __allowed_attribute_types__ = (ConsumedThingProperty, ConsumedThingAction, ConsumedThingEvent)
    __WRAPPER_ASSIGNMENTS__ =  ('__name__', '__qualname__', '__doc__')

    @classmethod
    def zmq(self, server_id: str, thing_id: str, protocol: str, **kwargs):
        from .proxy import ObjectProxy
        id = f"{server_id}|{thing_id}|{protocol}|{uuid.uuid4()}"
        object_proxy = ObjectProxy(id, **kwargs)
        sync_zmq_client = SyncZMQClient(
                                        f"{id}|sync",
                                        server_id=server_id,
                                        logger=object_proxy.logger,
                                        **kwargs
                                    )
        async_zmq_client = AsyncZMQClient(
                                        f"{id}|async",   
                                        server_id=server_id,                                            
                                        logger=object_proxy.logger,
                                        **kwargs
                                    )
        assert isinstance(Thing.get_thing_model, Action)
        FetchTDAffordance = Thing.get_thing_model.to_affordance()
        FetchTDAffordance._thing_id = thing_id
        FetchTD = ZMQAction(
            resource=FetchTDAffordance,
            sync_client=sync_zmq_client,
            async_client=async_zmq_client,
        )
        TD = FetchTD(ignore_errors=True)
        for name  in TD["properties"]:
            affordance = PropertyAffordance.from_TD(name, TD)
            consumed_property = ZMQProperty(
                                    resource=affordance, 
                                    sync_client=sync_zmq_client, 
                                    async_client=async_zmq_client,
                                    owner_inst=object_proxy,
                                    invokation_timeout=object_proxy.invokation_timeout,
                                    execution_timeout=object_proxy.execution_timeout,
                                )
            self.add_property(object_proxy, consumed_property)
        for action in TD["actions"]:
            affordance = ActionAffordance.from_TD(action, TD)
            consumed_action = ZMQAction(
                                    resource=affordance, 
                                    sync_client=sync_zmq_client, 
                                    async_client=async_zmq_client,
                                    owner_inst=object_proxy,
                                    invokation_timeout=object_proxy.invokation_timeout,
                                    execution_timeout=object_proxy.execution_timeout,
                                )
            self.add_action(object_proxy, consumed_action)
        for event in TD["events"]:
            affordance = EventAffordance.from_TD(event, TD)
            consumed_event = ZMQEvent(
                                    resource=affordance, 
                                    sync_zmq_client=sync_zmq_client,
                                    async_zmq_client=async_zmq_client,
                                    owner_inst=object_proxy,
                                    invokation_timeout=object_proxy.invokation_timeout,
                                    execution_timeout=object_proxy.execution_timeout,
                                )
            self.add_event(object_proxy, consumed_event)
        return object_proxy

    @classmethod
    def add_action(self, client, action: ConsumedThingAction) -> None:
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

    @classmethod
    def add_property(self, client, property: ConsumedThingProperty) -> None:
        # if not property_info.top_owner:
        #     return
        #     raise RuntimeError("logic error")
        # for attr in ['__doc__', '__name__']: 
        #     # just to imitate _add_method logic
        #     setattr(property, attr, property_info.get_dunder_attr(attr))
        setattr(client, property._resource.name, property)

    @classmethod
    def add_event(cls, client, event: ConsumedThingEvent) -> None:
        setattr(client, event._resource.name, event)
    


