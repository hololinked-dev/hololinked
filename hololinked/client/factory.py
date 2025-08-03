import uuid

from tornado.httpclient import HTTPClient, HTTPRequest, HTTPResponse
from tornado.simple_httpclient import HTTPTimeoutError

from ..core.zmq import SyncZMQClient, AsyncZMQClient
from ..core import Thing, Action
from ..td.interaction_affordance import PropertyAffordance, ActionAffordance, EventAffordance
from ..serializers import Serializers
from .abstractions import ConsumedThingAction, ConsumedThingProperty, ConsumedThingEvent
from .zmq.consumed_interactions import ZMQAction, ZMQEvent, ZMQProperty, WriteMultipleProperties, ReadMultipleProperties
from .http.consumed_interactions import HTTPProperty, HTTPAction, HTTPEvent


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
        object_proxy.td = TD
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
        for opname, ophandler in zip(['_get_properties', '_set_properties'], [ReadMultipleProperties, WriteMultipleProperties]):
            setattr(
                object_proxy, 
                opname,
                ophandler(
                    sync_client=sync_zmq_client, 
                    async_client=async_zmq_client, 
                    owner_inst=object_proxy
                )
            )
        return object_proxy
    
    @classmethod
    def http(self, url: str, **kwargs):
        from .proxy import ObjectProxy
        response = HTTPClient().fetch(HTTPRequest(url))
        assert response.code == 200, f"HTTP request failed with status code {response.code}"
        # assert response.headers.get('Content-Type') == 'application/json'
        TD = Serializers.json.loads(response.body)
        id = f"client|{TD['id']}|HTTP|{uuid.uuid4()}" 
        object_proxy = ObjectProxy(id, td=TD, **kwargs)
        for name in TD["properties"]:
            affordance = PropertyAffordance.from_TD(name, TD)
            consumed_property = HTTPProperty(
                                    resource=affordance, 
                                    connect_timeout=kwargs.get('connect_timeout', 60),
                                    request_timeout=kwargs.get('request_timeout', 60),
                                    invokation_timeout=kwargs.get('invokation_timeout', 5),
                                    execution_timeout=kwargs.get('execution_timeout', 5),
                                    owner_inst=object_proxy,
                                    logger=object_proxy.logger
                                )
            self.add_property(object_proxy, consumed_property)
        for action in TD["actions"]:
            affordance = ActionAffordance.from_TD(action, TD)
            consumed_action = HTTPAction(
                                    resource=affordance, 
                                    connect_timeout=kwargs.get('connect_timeout', 60),
                                    request_timeout=kwargs.get('request_timeout', 60),
                                    invokation_timeout=kwargs.get('invokation_timeout', 5),
                                    execution_timeout=kwargs.get('execution_timeout', 5),
                                    owner_inst=object_proxy,
                                    logger=object_proxy.logger
                                )
            self.add_action(object_proxy, consumed_action)
        for event in TD["events"]:
            affordance = EventAffordance.from_TD(event, TD)
            consumed_event = HTTPEvent(
                                    resource=affordance, 
                                    connect_timeout=None,
                                    request_timeout=None,
                                    invokation_timeout=kwargs.get('invokation_timeout', 5),
                                    execution_timeout=kwargs.get('execution_timeout', 5),
                                    owner_inst=object_proxy,
                                    logger=object_proxy.logger
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
    


