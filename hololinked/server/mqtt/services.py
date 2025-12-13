import copy

from typing import Any

import structlog

from ...constants import Operations
from ...td.interaction_affordance import EventAffordance, PropertyAffordance


class ThingDescriptionService:
    """Generates Thing Descriptions for Things"""

    def __init__(self, hostname: str, port: int, logger: structlog.stdlib.BoundLogger, ssl: bool = True) -> None:
        self.hostname = hostname
        self.port = port
        self.logger = logger
        self.ssl = ssl

    async def generate(
        self,
        ZMQ_TD: dict[str, Any],
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, Any]:
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
