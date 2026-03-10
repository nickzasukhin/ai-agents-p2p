"""Tests for Phase 12.4 — Zero-Config Go Online."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry
from src.network.tunnel import TunnelInfo


@pytest.fixture
def go_online_app(tmp_path, sample_agent_card):
    """Create a FastAPI app for go-online testing."""
    did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
    did_mgr.init()

    event_bus = EventBus(max_buffer=20)
    registry = StaticRegistry(registry_path=tmp_path / "registry.json")
    gossip = GossipProtocol(registry=registry, own_url="http://localhost:9000")

    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "profile.md").write_text("# Test\n")

    app = create_app(
        agent_card=sample_agent_card,
        did_manager=did_mgr,
        event_bus=event_bus,
        gossip=gossip,
        data_dir=str(tmp_path),
        own_url="http://localhost:9000",
    )
    return app


@pytest.fixture
async def go_online_client(go_online_app):
    """Async httpx test client."""
    transport = httpx.ASGITransport(app=go_online_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── GET /network/go-online/status Tests ──────────────────────

class TestGoOnlineStatus:
    async def test_status_returns_200(self, go_online_client):
        """GET /network/go-online/status should return 200."""
        resp = await go_online_client.get("/network/go-online/status")
        assert resp.status_code == 200

    async def test_status_shows_local(self, go_online_client):
        """Status should show not online when running locally."""
        resp = await go_online_client.get("/network/go-online/status")
        data = resp.json()
        assert "is_online" in data
        assert "public_url" in data
        assert "tunnel_active" in data
        assert data["tunnel_active"] is False

    async def test_status_has_required_fields(self, go_online_client):
        """Status should have all required fields."""
        resp = await go_online_client.get("/network/go-online/status")
        data = resp.json()
        assert "is_online" in data
        assert "public_url" in data
        assert "tunnel_active" in data
        assert "tunnel_provider" in data


# ── POST /network/go-online Tests ────────────────────────────

class TestGoOnlineEndpoint:
    @patch("src.network.tunnel.start_tunnel", new_callable=AsyncMock)
    async def test_go_online_with_tunnel(self, mock_tunnel, go_online_client):
        """Go online should try to start a tunnel when on localhost."""
        mock_tunnel.return_value = TunnelInfo(
            provider="bore",
            public_url="http://bore.pub:12345",
            process=MagicMock(),
        )

        resp = await go_online_client.post("/network/go-online")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"
        assert data["tunnel_started"] is True
        assert data["tunnel_provider"] == "bore"
        assert data["public_url"] == "http://bore.pub:12345"

    @patch("src.network.tunnel.start_tunnel", new_callable=AsyncMock)
    async def test_go_online_no_tunnel_available(self, mock_tunnel, go_online_client):
        """Go online should report local_only when no tunnel works."""
        mock_tunnel.return_value = None

        resp = await go_online_client.post("/network/go-online")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "local_only"
        assert data["tunnel_started"] is False
        assert data["tunnel_provider"] is None

    @patch("src.network.tunnel.start_tunnel", new_callable=AsyncMock)
    async def test_go_online_response_structure(self, mock_tunnel, go_online_client):
        """Go online response should have all required fields."""
        mock_tunnel.return_value = None
        resp = await go_online_client.post("/network/go-online")
        data = resp.json()
        assert "status" in data
        assert "public_url" in data
        assert "tunnel_provider" in data
        assert "tunnel_started" in data
        assert "registered_registries" in data
        assert "discovery_triggered" in data

    @patch("src.network.tunnel.start_tunnel", new_callable=AsyncMock)
    async def test_go_online_registered_registries_list(self, mock_tunnel, go_online_client):
        """Registered registries should be a list."""
        mock_tunnel.return_value = None
        resp = await go_online_client.post("/network/go-online")
        data = resp.json()
        assert isinstance(data["registered_registries"], list)


# ── Go Online with Public URL ─────────────────────────────────

class TestGoOnlinePublicURL:
    async def test_go_online_already_public(self, tmp_path, sample_agent_card):
        """Go online should skip tunnel when already on public URL."""
        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        registry = StaticRegistry(registry_path=tmp_path / "registry.json")
        gossip = GossipProtocol(registry=registry, own_url="https://agents.example.com")

        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()
        (ctx_dir / "profile.md").write_text("# Test\n")

        app = create_app(
            agent_card=sample_agent_card,
            did_manager=did_mgr,
            event_bus=event_bus,
            gossip=gossip,
            data_dir=str(tmp_path),
            own_url="https://agents.example.com",
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/network/go-online")
            data = resp.json()
            # Should not try tunnel since not localhost
            assert data["public_url"] == "https://agents.example.com"


# ── Auth Tests ────────────────────────────────────────────────

class TestGoOnlineAuth:
    async def test_go_online_status_no_auth(self, tmp_path, sample_agent_card):
        """GET /network/go-online/status should work without auth (GET = read-only)."""
        from src.agent.config import AgentConfig

        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        config = AgentConfig(api_token="secret")

        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()
        (ctx_dir / "profile.md").write_text("# Test\n")

        app = create_app(
            agent_card=sample_agent_card,
            did_manager=did_mgr,
            event_bus=event_bus,
            data_dir=str(tmp_path),
            own_url="http://localhost:9000",
            config=config,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/network/go-online/status")
            assert resp.status_code == 200

    async def test_go_online_post_requires_auth(self, tmp_path, sample_agent_card):
        """POST /network/go-online should require auth when token is set."""
        from src.agent.config import AgentConfig

        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        config = AgentConfig(api_token="secret")

        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()
        (ctx_dir / "profile.md").write_text("# Test\n")

        app = create_app(
            agent_card=sample_agent_card,
            did_manager=did_mgr,
            event_bus=event_bus,
            data_dir=str(tmp_path),
            own_url="http://localhost:9000",
            config=config,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Without token — rejected
            resp = await client.post("/network/go-online")
            assert resp.status_code == 401

            # With token — should pass auth
            resp = await client.post(
                "/network/go-online",
                headers={"Authorization": "Bearer secret"},
            )
            assert resp.status_code != 401
            assert resp.status_code != 403
