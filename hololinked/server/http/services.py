import copy

from typing import Any

import structlog

from ...constants import JSONSerializable, Operations
from ...core.zmq.message import ERROR, INVALID_MESSAGE, TIMEOUT
from ...serializers import Serializers
from ...serializers.payloads import SerializableData
from ...td import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from ...td.forms import Form
from ..repository import BrokerThing  # noqa: F401


try:
    from ..security import APIKeySecurity, Argon2BasicSecurity
except ImportError:
    Argon2BasicSecurity = None
    APIKeySecurity = None

try:
    from ..security import BcryptBasicSecurity
except ImportError:
    BcryptBasicSecurity = None


__error_message_types__ = [TIMEOUT, ERROR, INVALID_MESSAGE]


class ThingDescriptionService:
    """Service layer to generate HTTP TD"""

    def __init__(
        self,
        resource: InteractionAffordance,
        logger: structlog.stdlib.BoundLogger,
        config: Any,
        server: Any,
    ) -> None:
        from . import HTTPServer  # noqa: F401
        from .config import RuntimeConfig  # noqa: F401

        self.resource = resource  # type: InteractionAffordance
        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(layer="service", impl=self.__class__.__name__)
        self.thing = self.config.thing_repository[self.resource.thing_id]  # type: BrokerThing
        self.server = server  # type: HTTPServer

    async def generate(
        self,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
        use_localhost: bool = False,
        authority: str = None,
    ) -> dict[str, JSONSerializable]:
        """
        generate the HTTP Thing Description

        Parameters
        ----------
        ignore_errors: bool, default `False`
            if `True`, errors while generating metadata for an affordances is ignored
        skip_names: list[str], default `[]`
            list of affordance names to skip while generating the TD
        use_localhost: bool, default `False`
            if `True`, localhost is used in the TD URLs instead of the server's hostname.
        authority: str, optional
            custom authority (protocol + host + port) to be used in the TD URLs. If None, the machine's hostname is used.
        """
        ZMQ_TD = await self.get_ZMQ_TD(ignore_errors=ignore_errors, skip_names=skip_names)
        TD = copy.deepcopy(ZMQ_TD)

        self.add_properties(TD, ZMQ_TD, authority=authority, ignore_errors=ignore_errors, use_localhost=use_localhost)
        self.add_actions(TD, ZMQ_TD, authority=authority, ignore_errors=ignore_errors, use_localhost=use_localhost)
        self.add_events(TD, ZMQ_TD, authority=authority, ignore_errors=ignore_errors, use_localhost=use_localhost)
        self.add_top_level_forms(TD, authority=authority, use_localhost=use_localhost)
        self.add_security_definitions(TD)
        self.add_links(TD)

        return TD

    def add_properties(
        self,
        TD: dict[str, JSONSerializable],
        ZMQ_TD: dict[str, JSONSerializable],
        authority: str,
        ignore_errors: bool,
        use_localhost: bool,
    ) -> None:
        """
        add properties to the TD with forms

        Parameters
        ----------
        TD: dict[str, JSONSerializable]
            The Thing Description to which properties are to be added
        ZMQ_TD: dict[str, JSONSerializable]
            The ZMQ Thing Description from which properties are to be read
        authority: str
            authority (protocol + host + port) to be used in the TD URLs
        ignore_errors: bool
            if `True`, errors while generating metadata for an affordances is ignored
        use_localhost: bool
            if `True`, localhost is used in the TD URLs instead of the server's hostname
        """
        from .config import HandlerMetadata

        for name in ZMQ_TD.get("properties", []):
            affordance = PropertyAffordance.from_TD(name, ZMQ_TD)
            TD["properties"][name]["forms"] = []
            try:
                href = self.server.router.get_href_for_affordance(
                    affordance,
                    authority=authority,
                    use_localhost=use_localhost,
                )
                http_methods = (
                    self.server.router.get_injected_dependencies(affordance)
                    .get("metadata", HandlerMetadata())
                    .http_methods
                )  # type: tuple[str]
            except ValueError as ex:
                if ignore_errors:
                    self.logger.warning(f"could not get HTTP methods for property {name}, skipping...")
                    continue
                raise ex from None
            for http_method in http_methods:
                if http_method.upper() == "DELETE":
                    # currently not in spec although we support it
                    continue
                if affordance.readOnly and http_method.upper() != "GET":
                    break
                op = Operations.readproperty if http_method.upper() == "GET" else Operations.writeproperty
                form = affordance.retrieve_form(op)
                if not form:
                    form = Form()
                    form.op = op
                    form.contentType = Serializers.for_object(TD["id"], TD["title"], affordance.name).content_type
                form.href = href
                form.htv_methodName = http_method
                TD["properties"][name]["forms"].append(form.json())
            if affordance.observable:
                form = affordance.retrieve_form(Operations.observeproperty)
                if not form:
                    form = Form()
                    form.contentType = Serializers.for_object(TD["id"], TD["title"], affordance.name).content_type
                    form.op = Operations.observeproperty
                form.href = f"{href}/change-event"
                form.htv_methodName = "GET"
                form.subprotocol = "sse"
                TD["properties"][name]["forms"].append(form.json())

    def add_actions(
        self,
        TD: dict[str, JSONSerializable],
        ZMQ_TD: dict[str, JSONSerializable],
        authority: str,
        ignore_errors: bool,
        use_localhost: bool,
    ) -> None:
        """
        add actions to the TD with forms

        Parameters
        ----------
        TD: dict[str, JSONSerializable]
            The Thing Description to which actions are to be added
        ZMQ_TD: dict[str, JSONSerializable]
            The ZMQ Thing Description from which actions are to be read
        authority: str
            authority (protocol + host + port) to be used in the TD URLs
        ignore_errors: bool
            if `True`, errors while generating metadata for an affordances is ignored
        use_localhost: bool
            if `True`, localhost is used in the TD URLs instead of the server's hostname
        """
        from .config import HandlerMetadata

        for name in ZMQ_TD.get("actions", []):
            affordance = ActionAffordance.from_TD(name, ZMQ_TD)
            TD["actions"][name]["forms"] = []
            try:
                href = self.server.router.get_href_for_affordance(
                    affordance,
                    authority=authority,
                    use_localhost=use_localhost,
                )
                http_methods = (
                    self.server.router.get_injected_dependencies(affordance)
                    .get("metadata", HandlerMetadata())
                    .http_methods
                )  # type: tuple[str]
            except ValueError as ex:
                if ignore_errors:
                    self.logger.warning(f"could not get HTTP methods for action {name}, skipping...")
                    continue
                raise ex from None
            for http_method in http_methods:
                form = affordance.retrieve_form(Operations.invokeaction)
                if not form:
                    form = Form()
                    form.op = Operations.invokeaction
                    form.contentType = Serializers.for_object(TD["id"], TD["title"], affordance.name).content_type
                form.href = href
                form.htv_methodName = http_method
                TD["actions"][name]["forms"].append(form.json())

    def add_events(
        self,
        TD: dict[str, JSONSerializable],
        ZMQ_TD: dict[str, JSONSerializable],
        authority: str,
        ignore_errors: bool,
        use_localhost: bool,
    ) -> None:
        """
        add events to the TD with forms

        Parameters
        ----------
        TD: dict[str, JSONSerializable]
            The Thing Description to which events are to be added
        ZMQ_TD: dict[str, JSONSerializable]
            The ZMQ Thing Description from which events are to be read
        authority: str
            authority (protocol + host + port) to be used in the TD URLs
        ignore_errors: bool
            if `True`, errors while generating metadata for an affordances is ignored
        use_localhost: bool
            if `True`, localhost is used in the TD URLs instead of the server's hostname
        """
        from .config import HandlerMetadata

        for name in ZMQ_TD.get("events", []):
            affordance = EventAffordance.from_TD(name, ZMQ_TD)
            TD["events"][name]["forms"] = []
            try:
                href = self.server.router.get_href_for_affordance(
                    affordance,
                    authority=authority,
                    use_localhost=use_localhost,
                )
                http_methods = (
                    self.server.router.get_injected_dependencies(affordance)
                    .get("metadata", HandlerMetadata(http_methods=["GET"]))
                    .http_methods
                )  # type: tuple[str]
            except ValueError as ex:
                if ignore_errors:
                    self.logger.warning(f"could not get HTTP methods for event {name}, skipping...")
                    continue
                raise ex from None
            for http_method in http_methods:
                form = affordance.retrieve_form(Operations.subscribeevent)
                if not form:
                    form = Form()
                    form.op = Operations.subscribeevent
                    form.contentType = Serializers.for_object(TD["id"], TD["title"], affordance.name).content_type
                form.href = href
                form.htv_methodName = http_method
                form.subprotocol = "sse"
                TD["events"][name]["forms"].append(form.json())

    def add_top_level_forms(
        self,
        TD: dict[str, JSONSerializable],
        authority: str,
        use_localhost: bool,
    ) -> None:
        """adds top level forms for reading and writing multiple properties"""

        properties_end_point = f"{self.server.router.get_basepath(authority, use_localhost)}/{TD['id']}/properties"

        if TD.get("forms", None) is None:
            TD["forms"] = []

        readallproperties = Form()
        readallproperties.href = properties_end_point
        readallproperties.op = "readallproperties"
        readallproperties.htv_methodName = "GET"
        readallproperties.contentType = "application/json"
        TD["forms"].append(readallproperties.json())

        writeallproperties = Form()
        writeallproperties.href = properties_end_point
        writeallproperties.op = "writeallproperties"
        writeallproperties.htv_methodName = "PUT"
        writeallproperties.contentType = "application/json"
        TD["forms"].append(writeallproperties.json())

        readmultipleproperties = Form()
        readmultipleproperties.href = properties_end_point
        readmultipleproperties.op = "readmultipleproperties"
        readmultipleproperties.htv_methodName = "GET"
        readmultipleproperties.contentType = "application/json"
        TD["forms"].append(readmultipleproperties.json())

        writemultipleproperties = Form()
        writemultipleproperties.href = properties_end_point
        writemultipleproperties.op = "writemultipleproperties"
        writemultipleproperties.htv_methodName = "PATCH"
        writemultipleproperties.contentType = "application/json"
        TD["forms"].append(writemultipleproperties.json())

    def add_security_definitions(self, TD: dict[str, JSONSerializable]) -> None:
        """adds security definitions to the TD"""
        from ...td.security_definitions import (
            APIKeySecurityScheme,
            BasicSecurityScheme,
            NoSecurityScheme,
        )

        TD["securityDefinitions"] = dict()

        if not self.server.config.security_schemes:
            nosec = NoSecurityScheme()
            nosec.build()
            TD["security"] = ["nosec"]
            TD["securityDefinitions"]["nosec"] = nosec.json()
            return

        TD["security"] = []
        for scheme in self.server.config.security_schemes:
            if isinstance(scheme, (BcryptBasicSecurity, Argon2BasicSecurity)):
                sec = BasicSecurityScheme()
                sec.build()
                TD["securityDefinitions"][scheme.name] = sec.json()
                TD["security"].append(scheme.name)
            if isinstance(scheme, APIKeySecurity):
                sec = APIKeySecurityScheme()
                TD["securityDefinitions"][scheme.name] = sec.json()
                TD["security"].append(scheme.name)

    def add_links(self, TD: dict[str, JSONSerializable]) -> None:
        """adds custom links to the TD, override this in subclass"""
        pass

    async def get_ZMQ_TD(self, ignore_errors: bool = False, skip_names: list[str] = []) -> dict[str, JSONSerializable]:
        """fetch the TM or ZMQ in process queue TD"""
        response_message = await self.thing.execute(
            objekt=self.resource.name,
            operation=Operations.invokeaction,
            payload=SerializableData(value=dict(ignore_errors=ignore_errors, skip_names=skip_names, protocol="INPROC")),
        )
        if response_message.type in __error_message_types__:
            raise RuntimeError(f"error while fetching TD from thing - got {response_message.type} response")

        payload = self.thing.get_response_payload(response_message)
        if not isinstance(payload, SerializableData):
            raise ValueError("invalid payload received from thing")

        payload = payload.deserialize()
        if not isinstance(payload, dict):
            raise ValueError("invalid payload received from thing")
        return payload
