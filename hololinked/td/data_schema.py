from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field, RootModel

from ..constants import JSON, JSONSerializable
from ..core import Property
from ..core.properties import (
    Boolean,
    ClassSelector,
    Filename,
    Foldername,
    Integer,
    List,
    Number,
    Path,
    Selector,
    String,
    Tuple,
    TupleSelector,
    TypedDict,
    TypedKeyMappingsDict,
    TypedList,
)
from ..schema_validators.json_schema import JSONSchema
from ..utils import issubklass
from .base import Schema
from .utils import get_summary


class DataSchema(Schema):
    """
    Implements Data Schema, usually used to represent payloads of properties, actions and events in a
    WoT Thing Description.

    - [Vocabulary Definitions](https://www.w3.org/TR/wot-thing-description11/#sec-data-schema-vocabulary-definition)
    - [Supported Fields](https://www.w3.org/TR/wot-thing-description11/#data-schema-fields)
    """

    title: str = None
    titles: Optional[dict[str, str]] = None
    description: str = None
    descriptions: Optional[dict[str, str]] = None
    const: Optional[bool] = None
    default: Optional[Any] = None
    readOnly: Optional[bool] = None
    writeOnly: Optional[bool] = None
    # write only can be considered as actions with no return value, so not used in this repository
    format: Optional[str] = None
    unit: Optional[str] = None
    type: Optional[str] = None
    oneOf: Optional[list[JSON]] = None

    model_config = ConfigDict(extra="allow")
    _custom_schema_generators: ClassVar = dict()

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property: Property) -> None:
        """populates schema information from property descriptor object"""
        self.title = get_summary(property.doc)
        if property.constant:
            self.const = property.constant
        if property.readonly:
            self.readOnly = property.readonly
        if property.default is not None:
            self.default = property.default
        if property.doc:
            self.description = Schema.format_doc(property.doc)
            if self.title and self.description.startswith(self.title):
                self.description.lstrip(self.title)
                self.description.lstrip(".").lstrip()
                self.title = ""
        if property.metadata and property.metadata.get("unit", None) is not None:
            self.unit = property.metadata["unit"]
        if property.allow_None:
            if (hasattr(self, "type") and self.type is not None) or (hasattr(self, "oneOf") and self.oneOf):
                self._move_own_type_to_oneOf()
            if not hasattr(self, "oneOf") or self.oneOf is None:
                self.oneOf = []
            if not any(types.get("type", NotImplemented) in [None, "null"] for types in self.oneOf):
                self.oneOf.append(dict(type="null"))
        if not self.title:
            del self.title

    # & _ds prefix is used to avoid name conflicts with PropertyAffordance class
    # you dont know what you are building, whether the data schema or something else when viewed from property affordance
    def ds_build_from_property(self, property: Property) -> None:
        """
        generates the schema specific to the property type,
        calls `ds_build_fields_from_property()` after choosing the right type
        """
        if self._custom_schema_generators.get(property, NotImplemented) is not NotImplemented:
            data_schema = self._custom_schema_generators[property]()
        elif isinstance(property, Property) and property.model is not None:
            base_data_schema = DataSchema()
            if isinstance(property.model, dict):
                given_data_schema = property.model
            elif issubklass(property.model, (BaseModel, RootModel)):
                from .pydantic_extensions import type_to_dataschema

                given_data_schema = type_to_dataschema(property.model)
            if property.allow_None:
                base_data_schema.oneOf = []
                base_data_schema.oneOf.append(dict(type="null"))
            if base_data_schema.oneOf:  # allow_None = True
                base_data_schema.oneOf.append(given_data_schema)
            else:
                for key, value in given_data_schema.items():
                    setattr(base_data_schema, key, value)
            data_schema = base_data_schema
        elif isinstance(property, (String, Filename, Foldername, Path)):
            data_schema = StringSchema()
        elif isinstance(property, (Number, Integer)):
            data_schema = NumberSchema()
        elif isinstance(property, Boolean):
            data_schema = BooleanSchema()
        elif isinstance(property, (List, TypedList, Tuple, TupleSelector)):
            data_schema = ArraySchema()
        elif isinstance(property, Selector):
            data_schema = EnumSchema()
        elif isinstance(property, (TypedDict, TypedKeyMappingsDict)):
            data_schema = ObjectSchema()
        elif isinstance(property, ClassSelector):
            data_schema = SelectorSchema()
        else:
            raise TypeError(
                f"WoT schema generator for this descriptor/property is not implemented. name {property.name} & type {type(property)}"
            )

        data_schema.ds_build_fields_from_property(property)
        for field_name in data_schema.model_dump(exclude_unset=True).keys():
            field_value = getattr(data_schema, field_name, NotImplemented)
            if field_value is not NotImplemented:
                setattr(self, field_name, field_value)

    def _move_own_type_to_oneOf(self):
        """move a type to oneOf"""
        pass


class BooleanSchema(DataSchema):
    """
    boolean schema - https://www.w3.org/TR/wot-thing-description11/#booleanschema
    used by Boolean descriptor
    """

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property) -> None:
        """generates the schema"""
        self.type = "boolean"
        super().ds_build_fields_from_property(property)

    def _move_own_type_to_oneOf(self):
        if not hasattr(self, "type") or self.type is None:
            return
        if not hasattr(self, "oneOf") or self.oneOf is None:
            self.oneOf = []
        self.oneOf.append(dict(type=self.type))
        del self.type


class StringSchema(DataSchema):
    """
    string schema - https://www.w3.org/TR/wot-thing-description11/#stringschema
    used by String, Filename, Foldername, Path descriptors
    """

    pattern: Optional[str] = None
    minLength: Optional[int] = None
    maxLength: Optional[int] = None

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property) -> None:
        """generates the schema"""
        self.type = "string"
        if isinstance(property, String):
            if property.regex is not None:
                self.pattern = property.regex
        super().ds_build_fields_from_property(property)

    def _move_own_type_to_oneOf(self):
        if not hasattr(self, "type") or self.type is None:
            return
        if not hasattr(self, "oneOf") or self.oneOf is None:
            self.oneOf = []
        schema = dict(type=self.type)
        del self.type
        if self.pattern is not None:
            schema["pattern"] = self.pattern
            del self.pattern
        self.oneOf.append(schema)


class NumberSchema(DataSchema):
    """
    number schema - https://www.w3.org/TR/wot-thing-description11/#numberschema
    used by Number and Integer descriptors
    """

    minimum: Optional[int | float] = None
    maximum: Optional[int | float] = None
    exclusiveMinimum: Optional[int | float] = None
    exclusiveMaximum: Optional[int | float] = None
    multipleOf: Optional[int | float] = None

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property) -> None:
        """generates the schema"""
        if isinstance(property, Integer):
            self.type = "integer"
        elif isinstance(property, Number):  # dont change order - one is subclass of other
            self.type = "number"
        if property.bounds is not None:
            if isinstance(property.bounds[0], (int, float)):  # i.e. value is not None which is allowed by param
                if not property.inclusive_bounds[0]:
                    self.exclusiveMinimum = property.bounds[0]
                else:
                    self.minimum = property.bounds[0]
            if isinstance(property.bounds[1], (int, float)):
                if not property.inclusive_bounds[1]:
                    self.exclusiveMaximum = property.bounds[1]
                else:
                    self.maximum = property.bounds[1]
        if property.step:
            self.multipleOf = property.step
        super().ds_build_fields_from_property(property)

    def _move_own_type_to_oneOf(self):
        if not hasattr(self, "type") or self.type is None:
            return
        if not hasattr(self, "oneOf") or self.oneOf is None:
            self.oneOf = []
        schema = dict(type=self.type)
        del self.type
        for attr in ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"]:
            if hasattr(self, attr) and getattr(self, attr) is not None:
                schema[attr] = getattr(self, attr)
                delattr(self, attr)
        self.oneOf.append(schema)


class ArraySchema(DataSchema):
    """
    array schema - https://www.w3.org/TR/wot-thing-description11/#arrayschema
    Used by list, Tuple, TypedList and TupleSelector
    """

    items: Optional[DataSchema | list[DataSchema] | JSON | JSONSerializable] = None
    maxItems: Optional[int] = Field(None, ge=0)
    minItems: Optional[int] = Field(None, ge=0)

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property) -> None:
        """generates the schema"""
        self.type = "array"
        self.items = []
        if isinstance(property, (List, Tuple, TypedList)) and property.item_type is not None:
            if property.bounds:
                if property.bounds[0]:
                    self.minItems = property.bounds[0]
                if property.bounds[1]:
                    self.maxItems = property.bounds[1]
            if isinstance(property.item_type, (list, tuple)):
                for typ in property.item_type:
                    self.items.append(dict(type=JSONSchema.get_base_type(typ)))
            elif property.item_type is not None:
                self.items.append(dict(type=JSONSchema.get_base_type(property.item_type)))
        elif isinstance(property, TupleSelector):
            objects = list(property.objects)
            for obj in objects:
                if any(types["type"] == JSONSchema._replacements.get(type(obj), None) for types in self.items):
                    continue
                self.items.append(dict(type=JSONSchema.get_base_type(type(obj))))
        if len(self.items) == 0:
            del self.items
        elif len(self.items) > 1:
            self.items = dict(
                oneOf=self.items
            )  # just adds the key 'oneOf' to items if there is more than one item type
        super().ds_build_fields_from_property(property)

    def _move_own_type_to_oneOf(self):
        if not hasattr(self, "type") or self.type is None:
            return
        if not hasattr(self, "oneOf") or self.oneOf is None:
            self.oneOf = []
        schema = dict(type=self.type)
        del self.type
        for attr in ["items", "maxItems", "minItems"]:
            if hasattr(self, attr) and getattr(self, attr) is not None:
                schema[attr] = getattr(self, attr)
                delattr(self, attr)
        self.oneOf.append(schema)


class ObjectSchema(DataSchema):
    """
    object schema - https://www.w3.org/TR/wot-thing-description11/#objectschema
    Used by TypedDict where the key type must be a string
    """

    properties: Optional[JSON] = None
    required: Optional[list[str]] = None

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property) -> None:
        """generates the schema"""
        super().ds_build_fields_from_property(property)
        properties = None
        required = None
        if hasattr(property, "json_schema"):
            # Code will not reach here for now as have not implemented schema for typed dictionaries.
            properties = property.json_schema["properties"]
            if property.json_schema.get("required", NotImplemented) is not NotImplemented:
                required = property.json_schema["required"]
        if not property.allow_None:
            self.type = "object"
            if properties:
                self.properties = properties
            if required:
                self.required = required
        else:
            schema = dict(type="object")
            if properties:
                schema["properties"] = properties
            if required:
                schema["required"] = required
            self.oneOf.append(schema)


class SelectorSchema(DataSchema):
    """
    custom schema to deal with ClassSelector & Selector to fill oneOf field correctly
    https://www.w3.org/TR/wot-thing-description11/#dataschema
    """

    properties: Optional[JSON] = None
    required: Optional[list[str]] = None
    items: Optional[JSON | JSONSerializable] = None
    minItems: Optional[int] = None
    maxItems: Optional[int] = None
    # ClassSelector can technically have a JSON serializable as a class_

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property) -> None:
        """generates the schema"""
        self.oneOf = []
        if isinstance(property, ClassSelector):
            if not property.isinstance:
                raise NotImplementedError(
                    "WoT TD/TM for ClassSelector with isinstance set to True is not supported yet. "
                    + "Consider using this property in a different way if you want in the TD/TM."
                )
            if isinstance(property.class_, (list, tuple)):
                objects = list(property.class_)
            else:
                objects = [property.class_]
        elif isinstance(property, Selector):
            objects = list(property.objects)
        else:
            raise TypeError(
                f"EnumSchema and SelectorSchema supported only for Selector and ClassSelector. Given Type - {property}"
            )
        for obj in objects:
            if any(types["type"] == JSONSchema._replacements.get(type(obj), None) for types in self.oneOf):
                # just avoid duplicates of same type in oneOf
                continue
            if isinstance(property, ClassSelector):
                if not JSONSchema.is_allowed_type(obj):
                    raise TypeError(
                        f"Object for wot-td has invalid type for JSON conversion. Given type - {obj}. "
                        + "Use JSONSchema.register_replacements on hololinked.wot.td.JSONSchema object to recognise the type."
                    )
                subschema = dict(type=JSONSchema.get_base_type(obj))
                if JSONSchema.has_additional_schema_definitions(obj):
                    subschema.update(JSONSchema.get_additional_schema_definitions(obj))
                self.oneOf.append(subschema)
            elif isinstance(property, Selector):
                if JSONSchema.get_base_type(type(obj)) == "null":
                    continue
                self.oneOf.append(dict(type=JSONSchema.get_base_type(type(obj))))

        super().ds_build_fields_from_property(property)

        if len(self.oneOf) == 1:
            oneOf = self.oneOf[0]
            self.type = oneOf["type"]
            if oneOf["type"] == "object":
                if oneOf.get("properties", NotImplemented) is not NotImplemented:
                    self.properties = oneOf["properties"]
                if oneOf.get("required", NotImplemented) is not NotImplemented:
                    self.required = oneOf["required"]
            elif oneOf["type"] == "array":
                if oneOf.get("items", NotImplemented) is not NotImplemented:
                    self.items = oneOf["items"]
                if oneOf.get("maxItems", NotImplemented) is not NotImplemented:
                    self.minItems = oneOf["minItems"]
                if oneOf.get("maxItems", NotImplemented) is not NotImplemented:
                    self.maxItems = oneOf["maxItems"]
            del self.oneOf

    def _move_own_type_to_oneOf(self):
        pass


class EnumSchema(SelectorSchema):
    """
    custom schema to fill enum field correctly
    https://www.w3.org/TR/wot-thing-description11/#dataschema
    """

    enum: Optional[list[Any]] = None

    def __init__(self):
        super().__init__()

    def ds_build_fields_from_property(self, property) -> None:
        """generates the schema"""
        if not isinstance(property, Selector):
            raise TypeError(f"EnumSchema compatible property is only Selector, not {property.__class__}")
        self.enum = list(property.objects)
        super().ds_build_fields_from_property(property)

    def _move_own_type_to_oneOf(self):
        if hasattr(self, "type") and self.type is not None:
            schema = dict(type=self.type)
            del self.type
        elif hasattr(self, "oneOf") and self.oneOf:
            schema = dict(oneOf=self.oneOf)
            del self.oneOf
        else:
            schema = dict()
        if self.enum is not None:
            schema["enum"] = self.enum
            del self.enum
        if not hasattr(self, "oneOf") or self.oneOf is None:  # recreate for the null type
            self.oneOf = []
        if len(schema) > 0:  # i.e. the dict is populated
            self.oneOf.append(schema)
