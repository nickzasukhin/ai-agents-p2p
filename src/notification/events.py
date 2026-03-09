"""Event Bus — in-process pub/sub for AG-UI SSE notifications."""

from __future__ import annotations

import asyncio
import json
import structlog
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

log = structlog.get_logger()


class EventType(str, Enum):
    """AG-UI event types for owner notifications."""
    # Discovery events
    AGENT_DISCOVERED = "agent_discovered"
    AGENT_OFFLINE = "agent_offline"

    # Matching events
    MATCH_FOUND = "match_found"

    # Negotiation events
    NEGOTIATION_STARTED = "negotiation_started"
    NEGOTIATION_RECEIVED = "negotiation_received"
    NEGOTIATION_UPDATE = "negotiation_update"
    NEGOTIATION_ACCEPTED = "negotiation_accepted"
    NEGOTIATION_REJECTED = "negotiation_rejected"
    NEGOTIATION_TIMEOUT = "negotiation_timeout"

    # Owner action events
    MATCH_CONFIRMED = "match_confirmed"
    MATCH_DECLINED = "match_declined"

    # Profile events
    CARD_REGENERATED = "card_regenerated"

    # Network events (Phase 6.3)
    NETWORK_ADDRESS_RESOLVED = "network_address_resolved"
    NETWORK_TUNNEL_STARTED = "network_tunnel_started"
    NETWORK_RELAY_REGISTERED = "network_relay_registered"
    NETWORK_REACHABILITY_CHECK = "network_reachability_check"

    # Project events (Phase 6.4)
    PROJECT_CREATED = "project_created"
    PROJECT_RECRUITING = "project_recruiting"
    PROJECT_ACTIVE = "project_active"
    PROJECT_STALLED = "project_stalled"
    PROJECT_COMPLETED = "project_completed"
    PROJECT_SUGGESTION = "project_suggestion"

    # System events
    SYSTEM_ERROR = "system_error"
    DISCOVERY_CYCLE = "discovery_cycle"


@dataclass
class Event:
    """A single event in the event bus."""
    type: EventType
    data: dict
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: int = 0  # Auto-assigned sequence number

    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        payload = json.dumps({
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        })
        return f"id: {self.id}\nevent: {self.type.value}\ndata: {payload}\n\n"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class EventBus:
    """In-process event bus with SSE streaming support.

    Supports multiple concurrent subscribers (browser tabs, etc.).
    Events are buffered for replay to new subscribers.
    """

    def __init__(self, max_buffer: int = 200, storage=None, ws_manager=None):
        self._subscribers: list[asyncio.Queue] = []
        self._buffer: list[Event] = []
        self._max_buffer = max_buffer
        self._seq = 0
        self.storage = storage  # Optional Storage for persistence
        self.ws_manager = ws_manager  # Optional WSConnectionManager (Phase 6.8)

    def emit(self, event_type: EventType, data: dict) -> Event:
        """Emit an event to all subscribers."""
        self._seq += 1
        event = Event(type=event_type, data=data, id=self._seq)

        # Add to buffer
        self._buffer.append(event)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer:]

        # Persist to SQLite (fire-and-forget via task)
        if self.storage:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.storage.save_event(
                    event_type.value, data, event.timestamp,
                ))
            except RuntimeError:
                pass  # No running loop (e.g., during shutdown)

        # Push to SSE subscribers
        dead_queues = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead_queues.append(queue)

        for q in dead_queues:
            self._subscribers.remove(q)

        # Push to WebSocket clients (Phase 6.8)
        if self.ws_manager:
            self.ws_manager.push_event(event.to_dict())

        log.info("event_emitted", type=event_type.value,
                 sse_subscribers=len(self._subscribers),
                 ws_clients=self.ws_manager.client_count if self.ws_manager else 0)
        return event

    async def load_from_storage(self) -> int:
        """Load recent events from SQLite into buffer on startup."""
        if not self.storage:
            return 0
        rows = await self.storage.get_recent_events(count=self._max_buffer)
        for row in rows:
            self._seq += 1
            event = Event(
                type=EventType(row["type"]),
                data=row["data"],
                timestamp=row["timestamp"],
                id=self._seq,
            )
            self._buffer.append(event)
        log.info("events_loaded_from_storage", count=len(rows))
        return len(rows)

    async def subscribe(self, last_event_id: int = 0) -> AsyncIterator[Event]:
        """Subscribe to events as an async iterator.

        Args:
            last_event_id: Replay events after this ID (for reconnection).

        Yields:
            Event objects as they arrive.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)

        try:
            # Replay buffered events if requested
            if last_event_id > 0:
                for event in self._buffer:
                    if event.id > last_event_id:
                        yield event

            # Stream new events
            while True:
                event = await queue.get()
                yield event

        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def get_recent_events(self, count: int = 50, event_type: EventType | None = None) -> list[Event]:
        """Get recent events from the buffer."""
        events = self._buffer
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-count:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def total_events(self) -> int:
        return self._seq
