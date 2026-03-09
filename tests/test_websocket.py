"""Tests for WebSocket connection manager and endpoint."""

import asyncio
import json
import pytest

from src.notification.websocket import WSConnectionManager, WSClient, CHANNELS
from src.notification.events import EventBus, EventType
from src.server import create_app
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry

from starlette.testclient import TestClient


# ── Unit Tests: WSConnectionManager ─────────────────────────

class TestWSConnectionManager:
    def test_initial_state(self):
        mgr = WSConnectionManager()
        assert mgr.client_count == 0
        stats = mgr.get_stats()
        assert stats["connections"] == 0
        assert stats["batch_queue"] == 0
        assert set(stats["channels"]) == set(CHANNELS)

    def test_push_event_queues_to_batch(self):
        mgr = WSConnectionManager()
        mgr.push_event({"type": "match_found", "data": {}})
        assert len(mgr._batch) == 1

    def test_push_event_multiple(self):
        mgr = WSConnectionManager()
        for i in range(5):
            mgr.push_event({"type": f"event_{i}", "data": {}})
        assert len(mgr._batch) == 5

    def test_disconnect_unknown_client(self):
        mgr = WSConnectionManager()
        fake_client = WSClient(ws=None)
        mgr.disconnect(fake_client)
        assert mgr.client_count == 0


# ── Integration Tests: WebSocket Endpoint ────────────────────

@pytest.fixture
def ws_app(tmp_path, sample_agent_card):
    """Create a minimal FastAPI app for WS testing."""
    did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
    did_mgr.init()

    event_bus = EventBus(max_buffer=20)

    registry = StaticRegistry(registry_path=tmp_path / "registry.json")
    gossip = GossipProtocol(registry=registry, own_url="http://localhost:9000")

    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "profile.md").write_text("# Profile\n")
    (ctx_dir / "skills.md").write_text("# Skills\n")
    (ctx_dir / "needs.md").write_text("# Needs\n")

    app = create_app(
        agent_card=sample_agent_card,
        did_manager=did_mgr,
        event_bus=event_bus,
        gossip=gossip,
        data_dir=str(tmp_path),
    )
    app.state._event_bus = event_bus
    return app


class TestWebSocketEndpoint:
    def test_connect_receives_connected_message(self, ws_app):
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert "channels" in msg

    def test_connect_receives_initial_health(self, ws_app):
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws:
            connected = ws.receive_json()
            assert connected["type"] == "connected"
            health = ws.receive_json()
            assert health["type"] == "state"
            assert health["channel"] == "health"
            assert "agent" in health["data"]

    def test_subscribe_to_channels(self, ws_app):
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # initial health

            ws.send_json({"subscribe": ["events", "matches"]})
            msg = ws.receive_json()
            assert msg["type"] == "subscribed"
            assert set(msg["channels"]) == {"events", "matches"}

    def test_unsubscribe_from_channels(self, ws_app):
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # initial health

            ws.send_json({"unsubscribe": ["health", "negotiations"]})
            msg = ws.receive_json()
            assert msg["type"] == "subscribed"
            assert "health" not in msg["channels"]
            assert "negotiations" not in msg["channels"]

    def test_ping_pong(self, ws_app):
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # initial health

            ws.send_json({"ping": True})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_invalid_json_ignored(self, ws_app):
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # initial health

            ws.send_text("not json at all")
            # Should not crash; send a ping to confirm connection alive
            ws.send_json({"ping": True})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_subscribe_invalid_channels_filtered(self, ws_app):
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # initial health

            ws.send_json({"subscribe": ["events", "nonexistent", "matches"]})
            msg = ws.receive_json()
            assert msg["type"] == "subscribed"
            assert "nonexistent" not in msg["channels"]
            assert "events" in msg["channels"]

    def test_ws_manager_stats_in_health(self, ws_app):
        """Health endpoint should include websocket stats."""
        client = TestClient(ws_app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "websocket" in data
        assert "connections" in data["websocket"]

    def test_health_endpoint_still_works(self, ws_app):
        """SSE endpoints should still work alongside WebSocket."""
        client = TestClient(ws_app)
        resp = client.get("/events/recent")
        assert resp.status_code == 200

    def test_multiple_connections(self, ws_app):
        """Multiple WebSocket connections should work simultaneously."""
        client = TestClient(ws_app)
        with client.websocket_connect("/ws") as ws1:
            ws1.receive_json()  # connected
            ws1.receive_json()  # initial health

            with client.websocket_connect("/ws") as ws2:
                ws2.receive_json()  # connected
                ws2.receive_json()  # initial health

                # Both can ping
                ws1.send_json({"ping": True})
                msg1 = ws1.receive_json()
                assert msg1["type"] == "pong"

                ws2.send_json({"ping": True})
                msg2 = ws2.receive_json()
                assert msg2["type"] == "pong"


class TestEventBusWSIntegration:
    def test_eventbus_has_ws_manager(self, ws_app):
        """EventBus should have ws_manager wired after app creation."""
        event_bus = ws_app.state._event_bus
        assert event_bus.ws_manager is not None

    def test_eventbus_push_event_queues_to_ws(self, ws_app):
        """EventBus.emit() should queue events to ws_manager batch."""
        event_bus = ws_app.state._event_bus
        ws_mgr = event_bus.ws_manager

        initial_batch = len(ws_mgr._batch)
        event_bus.emit(EventType.MATCH_FOUND, {"agent": "test"})
        assert len(ws_mgr._batch) == initial_batch + 1

    def test_ws_manager_stats(self, ws_app):
        ws_mgr = ws_app.state.ws_manager
        stats = ws_mgr.get_stats()
        assert stats["connections"] == 0
        assert isinstance(stats["channels"], list)
