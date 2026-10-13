"""Unit tests for custom MQTT topic registration (Issue #134)."""

import asyncio

from unittest.mock import MagicMock, patch

import pytest

from hololinked.client.mqtt.consumed_interactions import MQTTConsumer
from hololinked.core import Event, Thing
from hololinked.core.properties import Number
from hololinked.metadata.td.interaction_affordance import PropertyAffordance
from hololinked.server.mqtt.handlers import TopicPublisher
from hololinked.server.mqtt.server import MQTTPublisher
from hololinked.server.mqtt.services import ThingDescriptionService
from hololinked.utils import uuid_hex


# ============================================================
# Test Thing with observable property and event
# ============================================================

class CustomTopicThing(Thing):
    """Thing with observable property and event for custom topic tests."""

    custom_prop = Number(default=0, observable=True)
    custom_event = Event(doc="test event for custom topic")


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def test_thing():
    return CustomTopicThing(id=f"test-custom-{uuid_hex()}")


@pytest.fixture
def publisher(test_thing):
    with patch("aiomqtt.Client"):
        pub = MQTTPublisher(
            hostname="localhost",
            port=1883,
            username="test",
            password="test",
            config={
                "topic_publisher": TopicPublisher,
                "qos": 1,
            },
        )
        pub.things[test_thing.id] = test_thing
        return pub


# ============================================================
# add_observable
# ============================================================

def test_add_observable_stores_custom_topic(publisher, test_thing):
    publisher.add_observable("custom_prop", test_thing, "custom/prop/topic")
    assert publisher.custom_topics[(test_thing.id, "custom_prop")] == "custom/prop/topic"


def test_add_observable_stores_custom_qos(publisher, test_thing):
    publisher.add_observable("custom_prop", test_thing, "custom/prop/topic", qos=2)
    assert publisher.custom_qos[(test_thing.id, "custom_prop")] == 2


def test_add_observable_does_not_store_qos_when_none(publisher, test_thing):
    publisher.add_observable("custom_prop", test_thing, "custom/prop/topic")
    assert (test_thing.id, "custom_prop") not in publisher.custom_qos


def test_add_observable_stores_custom_publisher(publisher, test_thing):
    class MyPublisher(TopicPublisher):
        pass

    publisher.add_observable(
        "custom_prop", test_thing, "custom/prop/topic", publisher=MyPublisher
    )
    assert publisher.custom_publishers[(test_thing.id, "custom_prop")] is MyPublisher


def test_add_observable_raises_type_error_for_invalid_thing(publisher):
    with pytest.raises(TypeError):
        publisher.add_observable("custom_prop", "not-a-thing", "topic")


def test_add_observable_raises_type_error_for_non_property(publisher, test_thing):
    with pytest.raises(TypeError):
        publisher.add_observable("non_existent", test_thing, "topic")


# ============================================================
# add_property (alias)
# ============================================================

def test_add_property_is_alias_for_add_observable(publisher, test_thing):
    publisher.add_property("custom_prop", test_thing, "custom/prop/topic")
    assert publisher.custom_topics[(test_thing.id, "custom_prop")] == "custom/prop/topic"


# ============================================================
# add_event
# ============================================================

def test_add_event_stores_custom_topic(publisher, test_thing):
    publisher.add_event("custom_event", test_thing, "custom/event/topic")
    assert publisher.custom_topics[(test_thing.id, "custom_event")] == "custom/event/topic"


def test_add_event_stores_custom_qos(publisher, test_thing):
    publisher.add_event("custom_event", test_thing, "custom/event/topic", qos=2)
    assert publisher.custom_qos[(test_thing.id, "custom_event")] == 2


def test_add_event_raises_type_error_for_invalid_thing(publisher):
    with pytest.raises(TypeError):
        publisher.add_event("custom_event", "not-a-thing", "topic")


# ============================================================
# ThingDescriptionService — custom topic в TD
# ============================================================

def test_generate_uses_custom_topic_for_property(test_thing):
    """TD form.mqv_topic should use custom topic for observable properties."""
    custom_topics = {(test_thing.id, "custom_prop"): "custom/prop/topic"}

    service = ThingDescriptionService(
        hostname="localhost",
        port=1883,
        logger=MagicMock(),
        thing=test_thing,
        ssl=False,
        use_websocket=False,
        custom_topics=custom_topics,
    )

    td = asyncio.run(service.generate())

    forms = td["properties"]["custom_prop"]["forms"]
    mqv_topics = [f.get("mqv:topic") or f.get("mqv_topic") for f in forms]
    assert "custom/prop/topic" in mqv_topics


def test_generate_uses_custom_topic_for_event(test_thing):
    """TD form.mqv_topic should use custom topic for events."""
    custom_topics = {(test_thing.id, "custom_event"): "custom/event/topic"}

    service = ThingDescriptionService(
        hostname="localhost",
        port=1883,
        logger=MagicMock(),
        thing=test_thing,
        ssl=False,
        use_websocket=False,
        custom_topics=custom_topics,
    )

    td = asyncio.run(service.generate())

    forms = td["events"]["custom_event"]["forms"]
    mqv_topics = [f.get("mqv:topic") or f.get("mqv_topic") for f in forms]
    assert "custom/event/topic" in mqv_topics


def test_generate_uses_default_topic_when_not_custom(test_thing):
    """TD form.mqv_topic should fall back to auto-generated topic."""
    service = ThingDescriptionService(
        hostname="localhost",
        port=1883,
        logger=MagicMock(),
        thing=test_thing,
        ssl=False,
        use_websocket=False,
        custom_topics={},
    )

    td = asyncio.run(service.generate())

    forms = td["properties"]["custom_prop"]["forms"]
    mqv_topics = [f.get("mqv:topic") or f.get("mqv_topic") for f in forms]
    assert f"{test_thing.id}/custom_prop" in mqv_topics


# ============================================================
# MQTTConsumer.unsubscribe — использует сохранённый topic
# ============================================================

def _make_consumer_with_topic(topic: str | None):
    """Helper: create MQTTConsumer with mocked clients and given stored topic."""
    sync_client = MagicMock()
    async_client = MagicMock()
    logger = MagicMock()
    resource = MagicMock(spec=PropertyAffordance)
    resource.thing_id = "test-thing"
    resource.name = "custom_prop"

    consumer = MQTTConsumer(
        sync_client=sync_client,
        async_client=async_client,
        resource=resource,
        qos=1,
        logger=logger,
        owner_inst=MagicMock(),
    )
    consumer.topic = topic
    return consumer


def test_unsubscribe_uses_stored_topic():
    """unsubscribe() should use stored topic if available."""
    consumer = _make_consumer_with_topic("custom/prop/topic")
    consumer.unsubscribe()
    consumer.sync_client.message_callback_remove.assert_called_once_with("custom/prop/topic")


def test_unsubscribe_falls_back_to_default_topic():
    """unsubscribe() should fall back to auto-generated topic when no stored topic."""
    consumer = _make_consumer_with_topic(None)
    consumer.unsubscribe()
    consumer.sync_client.message_callback_remove.assert_called_once_with("test-thing/custom_prop")