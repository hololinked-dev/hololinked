import asyncio
import threading
import traceback
import uuid
import warnings

from typing import Any, Callable

import structlog

from ...client.abstractions import (
    SSE,
    ConsumedThingAction,
    ConsumedThingEvent,
    ConsumedThingProperty,
    raise_local_exception,
)
from ...constants import Operations
from ...core import Action, Thing  # noqa: F401
from ...core.zmq.brokers import (
    AsyncEventConsumer,
    AsyncZMQClient,
    BreakLoop,
    EventConsumer,
    SyncZMQClient,
)
from ...core.zmq.message import (
    EMPTY_BYTE,
    ERROR,
    INVALID_MESSAGE,
    TIMEOUT,
    ResponseMessage,
)
from ...serializers.payloads import SerializableData
from ...td import ActionAffordance, EventAffordance, PropertyAffordance
from ...td.forms import Form
from ..exceptions import ReplyNotArrivedError


__error_message_types__ = [TIMEOUT, ERROR, INVALID_MESSAGE]


class ZMQConsumedAffordanceMixin:
    # A utility mixin class for ZMQ based affordances
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    __slots__ = [
        "resource",
        "logger",
        "schema_validator",
        "owner_inst",
        "__name__",
        "__qualname__",
        "__doc__",
        "_sync_zmq_client",
        "_async_zmq_client",
        "_invokation_timeout",
        "_execution_timeout",
        "_thing_execution_context",
        "_last_zmq_response",
    ]  # __slots__ dont support multiple inheritance

    def __init__(
        self,
        sync_client: SyncZMQClient,
        async_client: AsyncZMQClient | None = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        sync_client: SyncZMQClient
            synchronous ZMQ client
        async_client: AsyncZMQClient
            asynchronous ZMQ client for async calls
        kwargs:
            additional keyword arguments:

            - `invokation_timeout`: float, default 5.0
                timeout for invokation of action or property read/write
            - `execution_timeout`: float, default 5.0
                timeout for execution of action or property read/write
        """
        self._sync_zmq_client = sync_client
        self._async_zmq_client = async_client
        self._invokation_timeout = kwargs.get("invokation_timeout", 5.0)
        self._execution_timeout = kwargs.get("execution_timeout", 5.0)
        self._thing_execution_context = dict(fetch_execution_logs=False)
        self._last_zmq_response = None  # type: ResponseMessage | None

    def get_last_return_value(self, response: ResponseMessage, raise_exception: bool = False) -> Any:
        """
        cached return value of the last operation performed.

        Parameters
        ----------
        response: ResponseMessage
            last response message received from the server
        raise_exception: bool
            whether to raise exception if the last response was an error message
        """
        if response is None:
            raise RuntimeError("No last response available. Did you make an operation?")
        payload = response.payload.deserialize()
        preserialized_payload = response.preserialized_payload.value
        if response.type in __error_message_types__ and raise_exception:
            raise_local_exception(payload)
        if preserialized_payload != EMPTY_BYTE:
            if payload is None:
                return preserialized_payload
            return payload, preserialized_payload
        return payload

    @property
    def last_zmq_response(self) -> ResponseMessage:
        """cache of last message received for this property"""
        return self._last_zmq_response

    def read_reply(self, message_id: str, timeout: int = None) -> Any:
        if self.owner_inst._noblock_messages.get(message_id) != self:
            raise RuntimeError(f"Message ID {message_id} does not belong to this property.")
        response = self._sync_zmq_client.recv_response(message_id=message_id)
        if not response:
            raise ReplyNotArrivedError(f"could not fetch reply within timeout for message id '{message_id}'")
        self._last_zmq_response = response
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, response, True)


class ZMQAction(ZMQConsumedAffordanceMixin, ConsumedThingAction):
    # ZMQ method call abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(
        self,
        resource: ActionAffordance,
        sync_client: SyncZMQClient,
        async_client: AsyncZMQClient,
        owner_inst: Any,
        logger: structlog.stdlib.BoundLogger,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        resource: ActionAffordance
            dataclass object representing the action
        sync_client: SyncZMQClient
            synchronous ZMQ client
        async_zmq_client: AsyncZMQClient
            asynchronous ZMQ client for async calls
        owner_inst: Any
            the parent object that owns this action
        logger: structlog.stdlib.BoundLogger
            logger instance
        """
        ConsumedThingAction.__init__(self, resource=resource, owner_inst=owner_inst, logger=logger)
        ZMQConsumedAffordanceMixin.__init__(self, sync_client=sync_client, async_client=async_client, **kwargs)
        self.resource = resource

    last_return_value = property(
        fget=lambda self: ZMQConsumedAffordanceMixin.get_last_return_value(self, self._last_zmq_response, True),
        doc="cached return value of the last call to the method",
    )

    def __call__(self, *args, **kwargs) -> Any:
        if len(args) > 0:
            kwargs["__args__"] = args
        elif self.schema_validator:
            self.schema_validator.validate(kwargs)
        form = self.resource.retrieve_form(Operations.invokeaction, Form())
        # works over ThingModel, there can be a default empty form
        response = self._sync_zmq_client.execute(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.invokeaction,
            payload=SerializableData(value=kwargs, content_type=form.contentType or "application/json"),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self._last_zmq_response = response
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, response, True)

    async def async_call(self, *args, **kwargs) -> Any:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set True at __init__()")
        if len(args) > 0:
            kwargs["__args__"] = args
        elif self.schema_validator:
            self.schema_validator.validate(kwargs)
        response = await self._async_zmq_client.async_execute(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.invokeaction,
            payload=SerializableData(
                value=kwargs,
                content_type=self.resource.retrieve_form(Operations.invokeaction, Form()).contentType
                or "application/json",
            ),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self._last_zmq_response = response
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, response, True)

    def oneway(self, *args, **kwargs) -> None:
        if len(args) > 0:
            kwargs["__args__"] = args
        elif self.schema_validator:
            self.schema_validator.validate(kwargs)
        self._sync_zmq_client.send_request(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.invokeaction,
            payload=SerializableData(
                value=kwargs,
                content_type=self.resource.retrieve_form(Operations.invokeaction, Form()).contentType
                or "application/json",
            ),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
                oneway=True,
            ),
            thing_execution_context=self._thing_execution_context,
        )

    def noblock(self, *args, **kwargs) -> str:
        if len(args) > 0:
            kwargs["__args__"] = args
        elif self.schema_validator:
            self.schema_validator.validate(kwargs)
        msg_id = self._sync_zmq_client.send_request(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.invokeaction,
            payload=SerializableData(
                value=kwargs,
                content_type=self.resource.retrieve_form(Operations.invokeaction, Form()).contentType
                or "application/json",
            ),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self.owner_inst._noblock_messages[msg_id] = self
        return msg_id


class ZMQProperty(ZMQConsumedAffordanceMixin, ConsumedThingProperty):
    # property get set abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(
        self,
        resource: PropertyAffordance,
        sync_client: SyncZMQClient,
        async_client: AsyncZMQClient,
        owner_inst: Any,
        logger: structlog.stdlib.BoundLogger,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        resource: PropertyAffordance
            dataclass object representing the property
        sync_client: SyncZMQClient
            synchronous ZMQ client
        async_client: AsyncZMQClient
            asynchronous ZMQ client for async calls
        owner_inst: Any
            the parent object that owns this property
        logger: structlog.stdlib.BoundLogger
            logger instance for logging
        """
        ConsumedThingProperty.__init__(self, resource=resource, owner_inst=owner_inst, logger=logger)
        ZMQConsumedAffordanceMixin.__init__(self, sync_client=sync_client, async_client=async_client, **kwargs)
        self.resource = resource

    last_read_value = property(
        fget=lambda self: ZMQConsumedAffordanceMixin.get_last_return_value(self, self._last_zmq_response, True),
        doc="cached return value of the last call to the method",
    )

    def set(self, value: Any) -> None:
        response = self._sync_zmq_client.execute(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.writeproperty,
            payload=SerializableData(
                value=value,
                content_type=self.resource.retrieve_form(Operations.writeproperty, Form()).contentType
                or "application/json",
            ),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self._last_zmq_response = response
        ZMQConsumedAffordanceMixin.get_last_return_value(self, response, True)

    def get(self) -> Any:
        response = self._sync_zmq_client.execute(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.readproperty,
            server_execution_context=dict(
                invocation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self._last_zmq_response = response
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, response, True)

    async def async_set(self, value: Any) -> None:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        response = await self._async_zmq_client.async_execute(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.writeproperty,
            payload=SerializableData(
                value=value,
                content_type=self.resource.retrieve_form(Operations.writeproperty, Form()).contentType
                or "application/json",
            ),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self._last_zmq_response = response
        ZMQConsumedAffordanceMixin.get_last_return_value(self, response, True)

    async def async_get(self) -> Any:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        response = await self._async_zmq_client.async_execute(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.readproperty,
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self._last_zmq_response = response
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, response, True)

    def oneway_set(self, value: Any) -> None:
        self._sync_zmq_client.send_request(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.writeproperty,
            payload=SerializableData(
                value=value,
                content_type=self.resource.retrieve_form(Operations.writeproperty, Form()).contentType
                or "application/json",
            ),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
                oneway=True,
            ),
        )

    def noblock_get(self) -> str:
        msg_id = self._sync_zmq_client.send_request(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.readproperty,
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self.owner_inst._noblock_messages[msg_id] = self
        return msg_id

    def noblock_set(self, value: Any) -> None:
        msg_id = self._sync_zmq_client.send_request(
            thing_id=self.resource.thing_id,
            objekt=self.resource.name,
            operation=Operations.writeproperty,
            payload=SerializableData(
                value=value,
                content_type=self.resource.retrieve_form(Operations.writeproperty, Form()).contentType
                or "application/json",
            ),
            server_execution_context=dict(
                invokation_timeout=self._invokation_timeout,
                execution_timeout=self._execution_timeout,
            ),
            thing_execution_context=self._thing_execution_context,
        )
        self.owner_inst._noblock_messages[msg_id] = self
        return msg_id


class ZMQEvent(ConsumedThingEvent, ZMQConsumedAffordanceMixin):
    # Dont add class doc otherwise __doc__ in slots will conflict with class variable

    __slots__ = [
        "_subscribed",
    ]

    def __init__(
        self,
        resource: EventAffordance,
        logger: structlog.stdlib.BoundLogger,
        owner_inst: Any,
        **kwargs,
    ) -> None:
        ConsumedThingEvent.__init__(self, resource=resource, logger=logger, owner_inst=owner_inst)
        ZMQConsumedAffordanceMixin.__init__(self, sync_client=None, async_client=None, **kwargs)

    def listen(self, form: Form, callbacks: list[Callable], concurrent: bool, deserialize: bool) -> None:
        sync_event_client = EventConsumer(
            id=f"{self.resource.thing_id}|{self.resource.name}|sync|{uuid.uuid4().hex[:8]}",
            event_unique_identifier=f"{self.resource.thing_id}/{self.resource.name}",
            access_point=form.href,
            logger=self.logger,
        )
        sync_event_client.subscribe()
        task_id = threading.get_ident()
        self._subscribed[task_id] = (True, sync_event_client)
        while True:
            try:
                if not self._subscribed.get(task_id, (False, None))[0]:
                    break
                event_message = sync_event_client.receive(raise_interrupt_as_exception=True)
                if not event_message:
                    continue
                self._last_zmq_response = event_message
                event_data = SSE()
                event_data.id = event_message.id
                event_data.data = self.get_last_return_value(event_message, raise_exception=True)
                self.schedule_callbacks(callbacks, event_data, concurrent)
            except BreakLoop:
                break
            except Exception as ex:
                # traceback.print_exc()
                # TODO: some minor bug here within the zmq receive loop when the loop is interrupted
                # uncomment the above line to see the traceback
                warnings.warn(
                    f"Uncaught exception from {self.resource.name} event - {str(ex)}\n{traceback.print_exc()}",
                    category=RuntimeWarning,
                )

    async def async_listen(self, form: Form, callbacks: list[Callable], concurrent: bool, deserialize: bool) -> None:
        async_event_client = AsyncEventConsumer(
            id=f"{self.resource.thing_id}|{self.resource.name}|async|{uuid.uuid4().hex[:8]}",
            event_unique_identifier=f"{self.resource.thing_id}/{self.resource.name}",
            access_point=form.href,
            logger=self.logger,
        )
        async_event_client.subscribe()
        task_id = asyncio.current_task().get_name()
        self._subscribed[task_id] = (True, async_event_client)
        while True:
            try:
                if not self._subscribed.get(task_id, (False, None))[0]:
                    break
                event_message = await async_event_client.receive(raise_interrupt_as_exception=True)
                if not event_message:
                    continue
                self._last_zmq_response = event_message
                event_data = SSE()
                event_data.id = event_message.id
                event_data.data = self.get_last_return_value(event_message, raise_exception=True)
                await self.async_schedule_callbacks(callbacks, event_data, concurrent)
            except BreakLoop:
                break
            except Exception as ex:
                # traceback.print_exc()
                # if "There is no current event loop in thread" and not self._subscribed:
                #     # TODO: some minor bug here within the umq receive loop when the loop is interrupted
                #     # uncomment the above line to see the traceback
                #    pass
                # else:
                warnings.warn(
                    f"Uncaught exception from {self.resource.name} event - {str(ex)}\n{traceback.print_exc()}",
                    category=RuntimeWarning,
                )

    def unsubscribe(self) -> None:
        for task_id, (subscribed, client) in self._subscribed.items():
            if client:
                client.stop_polling()
        return super().unsubscribe()


class WriteMultipleProperties(ZMQAction):
    """
    Read and write multiple properties at once
    """

    def __init__(
        self,
        sync_client: SyncZMQClient,
        async_client: AsyncZMQClient | None = None,
        owner_inst: Any = None,
        **kwargs,
    ) -> None:
        action = Thing._set_properties  # type: Action
        resource = action.to_affordance(Thing)
        resource._thing_id = owner_inst.thing_id
        super().__init__(
            resource=resource,
            sync_client=sync_client,
            async_client=async_client,
            owner_inst=owner_inst,
            **kwargs,
        )


class ReadMultipleProperties(ZMQAction):
    """
    Read multiple properties at once
    """

    def __init__(
        self,
        sync_client: SyncZMQClient,
        async_client: AsyncZMQClient | None = None,
        owner_inst: Any = None,
        **kwargs,
    ) -> None:
        action = Thing._get_properties  # type: Action
        resource = action.to_affordance(Thing)
        resource._thing_id = owner_inst.thing_id
        super().__init__(
            resource=resource,
            sync_client=sync_client,
            async_client=async_client,
            owner_inst=owner_inst,
            **kwargs,
        )


__all__ = [
    ZMQAction.__name__,
    ZMQProperty.__name__,
    ZMQEvent.__name__,
]
