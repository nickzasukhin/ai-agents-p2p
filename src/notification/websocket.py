"""WebSocket connection manager for real-time push updates.

Manages multiple client connections with channel subscriptions,
event batching, and heartbeat/ping-pong for dead connection detection.
"""

from __future__ import annotations

import asyncio
import json
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

log = structlog.get_logger()

CHANNELS = ("events", "matches", "negotiations", "health")
BATCH_INTERVAL_S = 0.2
HEARTBEAT_INTERVAL_S = 30


@dataclass
class WSClient:
    """A single WebSocket client with channel subscriptions."""
    ws: WebSocket
    channels: set[str] = field(default_factory=lambda: set(CHANNELS))
    last_event_id: int = 0
    connected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class WSConnectionManager:
    """Manages WebSocket connections with channel subscriptions and batching.

    Features:
        - Channel subscriptions: clients choose which data types to receive
        - Batching: events accumulated for 200ms then flushed as one frame
        - Heartbeat: server pings every 30s to detect dead connections
        - Replay: clients can request missed events via last_event_id
    """

    def __init__(self):
        self._clients: list[WSClient] = []
        self._batch: list[dict] = []
        self._batch_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket, event_buffer: list | None = None) -> WSClient:
        """Accept a WebSocket connection and register the client."""
        await ws.accept()
        client = WSClient(ws=ws)
        self._clients.append(client)

        await self._send(client, {
            "type": "connected",
            "channels": list(CHANNELS),
            "subscribed": list(client.channels),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self._ensure_background_tasks()

        log.info("ws_client_connected", total=len(self._clients))
        return client

    def disconnect(self, client: WSClient) -> None:
        """Remove a client from the active list."""
        if client in self._clients:
            self._clients.remove(client)
        log.info("ws_client_disconnected", total=len(self._clients))

    async def handle_message(self, client: WSClient, raw: str) -> None:
        """Process an incoming message from a client."""
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return

        if "subscribe" in msg:
            channels = msg["subscribe"]
            if isinstance(channels, list):
                client.channels = {c for c in channels if c in CHANNELS}
                await self._send(client, {
                    "type": "subscribed",
                    "channels": list(client.channels),
                })

        elif "unsubscribe" in msg:
            channels = msg["unsubscribe"]
            if isinstance(channels, list):
                client.channels -= set(channels)
                await self._send(client, {
                    "type": "subscribed",
                    "channels": list(client.channels),
                })

        elif msg.get("ping"):
            await self._send(client, {"type": "pong"})

        elif "last_event_id" in msg:
            client.last_event_id = int(msg["last_event_id"])

    def push_event(self, event_dict: dict) -> None:
        """Queue an event for batched delivery to 'events' subscribers."""
        self._batch.append({"type": "event", "data": event_dict})

    async def push_state(self, channel: str, data) -> None:
        """Immediately push a state update to subscribers of a channel."""
        if channel not in CHANNELS:
            return

        msg = {"type": "state", "channel": channel, "data": data}
        dead: list[WSClient] = []

        for client in self._clients:
            if channel in client.channels:
                try:
                    await client.ws.send_json(msg)
                except Exception:
                    dead.append(client)

        for c in dead:
            self.disconnect(c)

    async def broadcast(self, msg: dict, channel: str | None = None) -> None:
        """Send a message to all clients (optionally filtered by channel)."""
        dead: list[WSClient] = []
        for client in self._clients:
            if channel and channel not in client.channels:
                continue
            try:
                await client.ws.send_json(msg)
            except Exception:
                dead.append(client)
        for c in dead:
            self.disconnect(c)

    # ── Background tasks ──────────────────────────────────────────

    def _ensure_background_tasks(self) -> None:
        """Start batch flusher and heartbeat if not running."""
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._batch_loop())
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _batch_loop(self) -> None:
        """Flush batched events every BATCH_INTERVAL_S."""
        while self._clients:
            await asyncio.sleep(BATCH_INTERVAL_S)
            if not self._batch:
                continue

            messages = self._batch[:]
            self._batch.clear()

            if len(messages) == 1:
                payload = messages[0]
            else:
                payload = {"type": "batch", "messages": messages}

            dead: list[WSClient] = []
            for client in self._clients:
                if "events" not in client.channels:
                    continue
                try:
                    await client.ws.send_json(payload)
                except Exception:
                    dead.append(client)

            for c in dead:
                self.disconnect(c)

    async def _heartbeat_loop(self) -> None:
        """Send ping to all clients every HEARTBEAT_INTERVAL_S."""
        while self._clients:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            dead: list[WSClient] = []
            for client in self._clients:
                try:
                    await client.ws.send_json({"type": "ping"})
                except Exception:
                    dead.append(client)
            for c in dead:
                self.disconnect(c)

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    async def _send(client: WSClient, msg: dict) -> None:
        """Send a JSON message to a single client."""
        try:
            await client.ws.send_json(msg)
        except Exception:
            pass

    def get_stats(self) -> dict:
        return {
            "connections": len(self._clients),
            "batch_queue": len(self._batch),
            "channels": list(CHANNELS),
        }
