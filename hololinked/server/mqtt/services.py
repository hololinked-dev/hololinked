import copy

from typing import Any

import structlog

from ...constants import Operations
from ...td.interaction_affordance import EventAffordance, PropertyAffordance


class ThingDescriptionService:
    """
    Generates Thing Descriptions for `Thing`s.
    This object would be a service in layered architecture.
    """

    def __init__(
        self,
        hostname: str,
        port: int,
        logger: structlog.stdlib.BoundLogger,
        ssl: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        hostname: str
            The MQTT broker hostname, to fill in the TD forms
        port: int
            The MQTT broker port, to fill in the TD forms
        logger: structlog.stdlib.BoundLogger
            The logger to use for logging messages
        ssl: bool
            Whether the broker is using SSL or not
        """
        self.hostname = hostname
        self.port = port
        self.logger = logger.bind(layer="service", impl=self.__class__.__name__)
        self.ssl = ssl

    async def generate(
        self,
        ZMQ_TD: dict[str, Any],
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, Any]:
        """
        Generates the Thing Description for the specified `Thing`, adds observable properties and events.

        Parameters
        ----------
        ZMQ_TD: dict[str, Any]
            The ZMQ Thing Description message received from ZMQ broker
        ignore_errors: bool
            Whether to ignore errors when adding properties/events to the TD
        skip_names: list[str]
            List of property/event names to skip when adding to the TD

        Returns
        -------
        dict[str, Any]
            The generated MQTT Thing Description
        """
        TD = copy.deepcopy(ZMQ_TD)
        # remove actions as they dont push events
        TD.pop("actions", None)

        self.add_properties(TD, ZMQ_TD, ignore_errors, skip_names)
        self.add_events(TD, ZMQ_TD, ignore_errors, skip_names)

        return TD

    def add_properties(
        self,
        TD: dict[str, Any],
        ZMQ_TD: dict[str, Any],
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> None:
        """
        Adds observable properties to the Thing Description with MQTT forms.

        Parameters
        ----------
        TD: dict[str, Any]
            The seed Thing Description to modify in place. This method does not have a return value, therefore
            just supply the TD dict and it will be modified. Non-observable properties will be removed.
        ZMQ_TD: dict[str, Any]
            The ZMQ Thing Description message received from ZMQ broker
        ignore_errors: bool
            Whether to ignore errors when adding properties to the TD
        skip_names: list[str]
            List of property names to skip when adding to the TD
        """
        for name in ZMQ_TD.get("properties", {}).keys():
            if name in skip_names:
                continue
            try:
                affordance = PropertyAffordance.from_TD(name, ZMQ_TD)
                if not affordance.observable:
                    TD["properties"].pop(name)
                    continue
                TD["properties"][name]["forms"] = []
                form = affordance.retrieve_form(Operations.observeproperty)
                form.href = f"mqtt{'s' if self.ssl else ''}://{self.hostname}:{self.port}"
                form.mqv_topic = f"{TD['id']}/{name}"
                TD["properties"][name]["forms"].append(form.json())
            except Exception as ex:
                if ignore_errors:
                    self.logger.warning(f"Could not add property {name} to MQTT TD: {ex}")
                    continue
                raise ex from None

    def add_events(
        self,
        TD: dict[str, Any],
        ZMQ_TD: dict[str, Any],
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> None:
        """
        Adds events to the Thing Description with MQTT forms.

        Parameters
        ----------
        TD: dict[str, Any]
            The seed Thing Description to modify in place. This method does not have a return value, therefore
            just supply the TD dict and it will be modified.
        ZMQ_TD: dict[str, Any]
            The ZMQ Thing Description message received from ZMQ broker
        ignore_errors: bool
            Whether to ignore errors when adding events to the TD
        skip_names: list[str]
            List of event names to skip when adding to the TD
        """
        # repurpose event
        for name in ZMQ_TD.get("events", {}).keys():
            if name in skip_names:
                continue
            try:
                affordance = EventAffordance.from_TD(name, ZMQ_TD)
                TD["events"][name]["forms"] = []
                form = affordance.retrieve_form(Operations.subscribeevent)
                form.href = f"mqtt{'s' if self.ssl else ''}://{self.hostname}:{self.port}"
                form.mqv_topic = f"{TD['id']}/{name}"
                TD["events"][name]["forms"].append(form.json())
            except Exception as ex:
                if ignore_errors:
                    self.logger.warning(f"Could not add event {name} to MQTT TD: {ex}")
                    continue
                raise ex from None
