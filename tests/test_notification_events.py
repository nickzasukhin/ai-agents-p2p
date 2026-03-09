"""Tests for EventBus — emit, subscribe, buffer, replay."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.notification.events import EventBus, EventType, Event


class TestEvent:
    def test_to_sse_format(self):
        event = Event(type=EventType.MATCH_FOUND, data={"agent": "test"}, id=1)
        sse = event.to_sse()
        assert "id: 1" in sse
        assert "event: match_found" in sse
        assert "data:" in sse
        assert sse.endswith("\n\n")

    def test_to_dict(self):
        event = Event(type=EventType.MATCH_FOUND, data={"x": 1}, id=5)
        d = event.to_dict()
        assert d["id"] == 5
        assert d["type"] == "match_found"
        assert d["data"] == {"x": 1}


class TestEventType:
    def test_values(self):
        assert EventType.MATCH_FOUND.value == "match_found"
        assert EventType.CARD_REGENERATED.value == "card_regenerated"
        assert EventType.NEGOTIATION_STARTED.value == "negotiation_started"


class TestEventBusEmit:
    def test_emit_increments_sequence(self, event_bus):
        e1 = event_bus.emit(EventType.MATCH_FOUND, {"a": 1})
        e2 = event_bus.emit(EventType.MATCH_FOUND, {"a": 2})
        assert e2.id == e1.id + 1

    def test_emit_adds_to_buffer(self, event_bus):
        for i in range(3):
            event_bus.emit(EventType.MATCH_FOUND, {"i": i})
        events = event_bus.get_recent_events(10)
        assert len(events) == 3

    def test_emit_buffer_caps_at_max(self):
        bus = EventBus(max_buffer=5)
        for i in range(10):
            bus.emit(EventType.MATCH_FOUND, {"i": i})
        events = bus.get_recent_events(20)
        assert len(events) == 5

    def test_total_events_property(self, event_bus):
        for _ in range(5):
            event_bus.emit(EventType.MATCH_FOUND, {})
        assert event_bus.total_events == 5


class TestEventBusSubscribe:
    async def test_subscribe_receives_event(self, event_bus):
        received = []

        async def consumer():
            async for event in event_bus.subscribe():
                received.append(event)
                break  # get one then stop

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        event_bus.emit(EventType.MATCH_FOUND, {"test": True})
        await asyncio.wait_for(task, timeout=2.0)
        assert len(received) == 1
        assert received[0].data == {"test": True}

    def test_subscriber_count(self, event_bus):
        assert event_bus.subscriber_count == 0


class TestEventBusFilter:
    def test_get_recent_with_type_filter(self, event_bus):
        event_bus.emit(EventType.MATCH_FOUND, {"a": 1})
        event_bus.emit(EventType.NEGOTIATION_STARTED, {"b": 2})
        event_bus.emit(EventType.MATCH_FOUND, {"c": 3})

        matches = event_bus.get_recent_events(10, event_type=EventType.MATCH_FOUND)
        assert len(matches) == 2
        assert all(e.type == EventType.MATCH_FOUND for e in matches)
