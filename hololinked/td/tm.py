import typing
from pydantic import Field, ConfigDict

from .base import Schema
from .data_schema import DataSchema
from .metadata import VersionInfo
from .interaction_affordance import PropertyAffordance, ActionAffordance, EventAffordance
from ..core.state_machine import BoundFSM
from ..core import Thing


class ThingModel(Schema):
    """
    Thing Model as per W3C WoT Thing Description v1.1

    [Specification](https://www.w3.org/TR/wot-thing-description11/) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/ThingModel.pdf) <br>
    """

    context: typing.List[str | typing.Dict[str, str]] = Field(["https://www.w3.org/2022/wot/td/v1.1"], alias="@context")
    type: typing.Optional[typing.Union[str, typing.List[str]]] = None
    id: str = None
    title: str = None
    description: typing.Optional[str] = None
    version: typing.Optional[VersionInfo] = None
    created: typing.Optional[str] = None
    modified: typing.Optional[str] = None
    support: typing.Optional[str] = None
    base: typing.Optional[str] = None
    properties: typing.Dict[str, DataSchema] = Field(default_factory=dict)
    actions: typing.Dict[str, ActionAffordance] = Field(default_factory=dict)
    events: typing.Dict[str, EventAffordance] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    def __init__(
        self,
        instance: "Thing",
        allow_loose_schema: typing.Optional[bool] = False,
        ignore_errors: bool = False,
        skip_names: typing.Optional[list[str]] = [],
    ) -> None:
        super().__init__()
        self.instance = instance
        self.allow_loose_schema = allow_loose_schema
        self.ignore_errors = ignore_errors
        self.skip_names = skip_names or []

    def generate(self) -> "ThingModel":
        """create thing model"""
        self.id = self.instance.id
        self.title = self.instance.__class__.__name__
        self.context = ["https://www.w3.org/2022/wot/td/v1.1"]
        # default value of context is not being picked up although we only use exclude_unset=True
        if self.instance.__doc__:
            self.description = Schema.format_doc(self.instance.__doc__)
        self.properties = dict()
        self.actions = dict()
        self.events = dict()
        self.add_interaction_affordances()
        return self

    def produce(self) -> Thing:
        raise NotImplementedError("This will be implemented in a future release for an API first approach")

    # not the best code and logic, but works for now
    skip_properties: typing.List[str] = ["expose", "thing_description", "GUI", "object_info"]
    skip_actions: typing.List[str] = [
        Thing._add_property.name,
        Thing._get_properties.name,
        Thing._get_properties_in_db.name,
        Thing._set_properties.name,
        "get_postman_collection",
        "get_our_thing_model",
    ]
    skip_events: typing.List[str] = []

    def add_interaction_affordances(self):
        """add interaction affordances to thing model"""
        for affordance, items, affordance_cls, skip_list in [
            ["properties", self.instance.properties.remote_objects.items(), PropertyAffordance, self.skip_properties],
            ["actions", self.instance.actions.descriptors.items(), ActionAffordance, self.skip_actions],
            ["events", self.instance.events.plain.items(), EventAffordance, self.skip_events],
        ]:
            for name, obj in items:
                if name in skip_list or name in self.skip_names:
                    continue
                if (
                    name == "state"
                    and affordance == "properties"
                    and (
                        not hasattr(self.instance, "state_machine")
                        or not isinstance(self.instance.state_machine, BoundFSM)
                    )
                ):
                    continue
                try:
                    affordance_dict = getattr(self, affordance)
                    affordance_dict[name] = affordance_cls.generate(obj, self.instance)
                except Exception as ex:
                    if not self.ignore_errors:
                        raise ex from None
                    self.instance.logger.error(f"Error while generating schema for {name} - {ex}")

    def model_dump(self, **kwargs) -> dict[str, typing.Any]:
        """Return the JSON representation of the schema"""

        def dump_value(value):
            nonlocal kwargs
            if hasattr(value, "model_dump"):
                return value.model_dump(**kwargs)
            elif isinstance(value, dict):
                return {k: dump_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [dump_value(v) for v in value]
            elif isinstance(value, tuple):
                return tuple(dump_value(v) for v in value)
            else:
                return value

        result = {}
        for field in self.model_fields:
            if field in self.skip_keys:
                continue
            if not hasattr(self, field) or getattr(self, field) is None:
                continue
            if field in [
                "instance",
                "skip_keys",
                "skip_properties",
                "skip_actions",
                "skip_events",
                "skip_names",
                "ignore_errors",
                "allow_loose_schema",
            ]:
                continue
            value = getattr(self, field)
            result[field] = dump_value(value)
        return result
