"""Service layer that generates the Thing Description served over HTTP."""

import copy

from typing import Any, cast

import structlog

from hololinked import Serializers

from ...constants import JSONSerializable, Operations
from ...metadata.td import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from ...metadata.td.forms import Form
from ..security import (
    APIKeySecurity,
    Argon2BasicSecurity,
    BcryptBasicSecurity,
    OIDCSecurity,
)


class ThingDescriptionService:
    """Service layer to generate HTTP TD."""

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
        self.engine = self.config.engine
        self.server = server  # type: HTTPServer

    async def generate(
        self,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
        use_localhost: bool = False,
        authority: str | None = None,
    ) -> dict[str, JSONSerializable]:
        """
        Generate the HTTP Thing Description.

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

        Returns
        -------
        dict[str, JSONSerializable]
            the Thing Description, with HTTP forms added to every affordance
        """
        thing_model = self.get_thing_model(ignore_errors=ignore_errors, skip_names=skip_names)
        TD = copy.deepcopy(thing_model)

        self.add_properties(
            TD, thing_model, authority=authority, ignore_errors=ignore_errors, use_localhost=use_localhost
        )
        self.add_actions(TD, thing_model, authority=authority, ignore_errors=ignore_errors, use_localhost=use_localhost)
        self.add_events(TD, thing_model, authority=authority, ignore_errors=ignore_errors, use_localhost=use_localhost)
        self.add_top_level_forms(TD, authority=authority, use_localhost=use_localhost)
        self.add_security_definitions(TD)
        self.add_links(TD)

        return TD

    def add_properties(
        self,
        TD: dict[str, JSONSerializable],
        thing_model: dict[str, JSONSerializable],
        authority: str | None,
        ignore_errors: bool,
        use_localhost: bool,
    ) -> None:
        """
        Add properties to the TD with forms.

        Parameters
        ----------
        TD: dict[str, JSONSerializable]
            The Thing Description to which properties are to be added
        thing_model: dict[str, JSONSerializable]
            The Thing Model from which properties are to be read
        authority: str
            authority (protocol + host + port) to be used in the TD URLs
        ignore_errors: bool
            if `True`, errors while generating metadata for an affordances is ignored
        use_localhost: bool
            if `True`, localhost is used in the TD URLs instead of the server's hostname
        """
        from .config import HandlerMetadata

        thing_id = cast(str, TD["id"])
        title = cast(str, TD["title"])
        properties = cast(dict[str, Any], TD["properties"])

        for name in cast(dict[str, Any], thing_model.get("properties", {})):
            affordance = PropertyAffordance.from_TD(name, thing_model)
            forms = []  # type: list[JSONSerializable]
            properties[name]["forms"] = forms
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
                    form.contentType = Serializers.for_object(thing_id, title, affordance.name).content_type
                form.href = href
                form.htv_methodName = http_method
                forms.append(form.json())
            if affordance.observable:
                form = affordance.retrieve_form(Operations.observeproperty)
                if not form:
                    form = Form()
                    form.contentType = Serializers.for_object(thing_id, title, affordance.name).content_type
                    form.op = Operations.observeproperty
                form.href = f"{href}/change-event"
                form.htv_methodName = "GET"
                form.subprotocol = "sse"
                forms.append(form.json())

    def add_actions(
        self,
        TD: dict[str, JSONSerializable],
        thing_model: dict[str, JSONSerializable],
        authority: str | None,
        ignore_errors: bool,
        use_localhost: bool,
    ) -> None:
        """
        Add actions to the TD with forms.

        Parameters
        ----------
        TD: dict[str, JSONSerializable]
            The Thing Description to which actions are to be added
        thing_model: dict[str, JSONSerializable]
            The Thing Model from which actions are to be read
        authority: str
            authority (protocol + host + port) to be used in the TD URLs
        ignore_errors: bool
            if `True`, errors while generating metadata for an affordances is ignored
        use_localhost: bool
            if `True`, localhost is used in the TD URLs instead of the server's hostname
        """
        from .config import HandlerMetadata

        thing_id = cast(str, TD["id"])
        title = cast(str, TD["title"])
        actions = cast(dict[str, Any], TD["actions"])

        for name in cast(dict[str, Any], thing_model.get("actions", {})):
            affordance = ActionAffordance.from_TD(name, thing_model)
            forms = []  # type: list[JSONSerializable]
            actions[name]["forms"] = forms
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
                    form.contentType = Serializers.for_object(thing_id, title, affordance.name).content_type
                form.href = href
                form.htv_methodName = http_method
                forms.append(form.json())

    def add_events(
        self,
        TD: dict[str, JSONSerializable],
        thing_model: dict[str, JSONSerializable],
        authority: str | None,
        ignore_errors: bool,
        use_localhost: bool,
    ) -> None:
        """
        Add events to the TD with forms.

        Parameters
        ----------
        TD: dict[str, JSONSerializable]
            The Thing Description to which events are to be added
        thing_model: dict[str, JSONSerializable]
            The Thing Model from which events are to be read
        authority: str
            authority (protocol + host + port) to be used in the TD URLs
        ignore_errors: bool
            if `True`, errors while generating metadata for an affordances is ignored
        use_localhost: bool
            if `True`, localhost is used in the TD URLs instead of the server's hostname
        """
        from .config import HandlerMetadata

        thing_id = cast(str, TD["id"])
        title = cast(str, TD["title"])
        events = cast(dict[str, Any], TD["events"])

        for name in cast(dict[str, Any], thing_model.get("events", {})):
            affordance = EventAffordance.from_TD(name, thing_model)
            forms = []  # type: list[JSONSerializable]
            events[name]["forms"] = forms
            try:
                href = self.server.router.get_href_for_affordance(
                    affordance,
                    authority=authority,
                    use_localhost=use_localhost,
                )
                http_methods = (
                    self.server.router.get_injected_dependencies(affordance)
                    .get("metadata", HandlerMetadata(http_methods=("GET",)))
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
                    form.contentType = Serializers.for_object(thing_id, title, affordance.name).content_type
                form.href = href
                form.htv_methodName = http_method
                form.subprotocol = "sse"
                forms.append(form.json())

    def add_top_level_forms(
        self,
        TD: dict[str, JSONSerializable],
        authority: str | None,
        use_localhost: bool,
    ) -> None:
        """Adds top level forms for reading and writing multiple properties."""
        properties_end_point = f"{self.server.router.get_basepath(authority, use_localhost)}/{TD['id']}/properties"

        if TD.get("forms", None) is None:
            TD["forms"] = []
        forms = cast(list[JSONSerializable], TD["forms"])

        readallproperties = Form()
        readallproperties.href = properties_end_point
        readallproperties.op = "readallproperties"
        readallproperties.htv_methodName = "GET"
        readallproperties.contentType = "application/json"
        forms.append(readallproperties.json())

        writeallproperties = Form()
        writeallproperties.href = properties_end_point
        writeallproperties.op = "writeallproperties"
        writeallproperties.htv_methodName = "PUT"
        writeallproperties.contentType = "application/json"
        forms.append(writeallproperties.json())

        readmultipleproperties = Form()
        readmultipleproperties.href = properties_end_point
        readmultipleproperties.op = "readmultipleproperties"
        readmultipleproperties.htv_methodName = "GET"
        readmultipleproperties.contentType = "application/json"
        forms.append(readmultipleproperties.json())

        writemultipleproperties = Form()
        writemultipleproperties.href = properties_end_point
        writemultipleproperties.op = "writemultipleproperties"
        writemultipleproperties.htv_methodName = "PATCH"
        writemultipleproperties.contentType = "application/json"
        forms.append(writemultipleproperties.json())

    def add_security_definitions(self, TD: dict[str, JSONSerializable]) -> None:
        """Adds security definitions to the TD."""
        from ...metadata.td.security_definitions import (
            APIKeySecurityScheme,
            BasicSecurityScheme,
            NoSecurityScheme,
            OIDCSecurityScheme,
        )

        security_definitions = dict()  # type: dict[str, JSONSerializable]
        security = []  # type: list[JSONSerializable]
        TD["securityDefinitions"] = security_definitions
        TD["security"] = security

        if not self.server.config.security_schemes:
            nosec = NoSecurityScheme()
            nosec.build()
            security.append("nosec")
            security_definitions["nosec"] = nosec.json()
            return

        for scheme in self.server.config.security_schemes:
            if isinstance(scheme, (BcryptBasicSecurity, Argon2BasicSecurity)):
                sec = BasicSecurityScheme()
                sec.build()
                security_definitions[scheme.name] = sec.json()
                security.append(scheme.name)
            if isinstance(scheme, APIKeySecurity):
                sec = APIKeySecurityScheme()
                security_definitions[scheme.name] = sec.json()
                security.append(scheme.name)
            if isinstance(scheme, OIDCSecurity):
                oidc_sec = OIDCSecurityScheme()
                oidc_sec.token = f"{scheme.issuer}/protocol/openid-connect/token"
                security_definitions[scheme.name] = oidc_sec.json()
                security.append(scheme.name)

    def add_links(self, TD: dict[str, JSONSerializable]) -> None:
        """Adds custom links to the TD, override this in subclass."""
        pass

    def get_thing_model(
        self,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, JSONSerializable]:
        """
        Fetch the served `Thing`'s Thing Model, which this service adds HTTP forms to.

        A Thing Model is the affordances without the forms, so there is nothing protocol-specific to
        strip - the previous version fetched a ZMQ Thing Description over a socket and then threw
        every one of its forms away.

        Parameters
        ----------
        ignore_errors: bool, default `False`
            if `True`, affordances whose metadata cannot be generated are skipped
        skip_names: list[str], default `[]`
            affordance names to leave out

        Returns
        -------
        dict[str, JSONSerializable]
            the Thing Model
        """
        return self.engine.get_thing_model(
            self.resource.thing_id,
            ignore_errors=ignore_errors,
            skip_names=skip_names,
        )
