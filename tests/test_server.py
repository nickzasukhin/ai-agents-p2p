"""Integration tests for FastAPI server — all endpoints."""

import json
import pytest
import httpx
from pathlib import Path

from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry

pytestmark = pytest.mark.integration


@pytest.fixture
def app_deps(tmp_path, sample_agent_card):
    """Create a minimal FastAPI app with real lightweight dependencies."""
    # DID manager
    did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
    did_mgr.init()

    # Event bus
    event_bus = EventBus(max_buffer=20)

    # Gossip
    registry = StaticRegistry(registry_path=tmp_path / "registry.json")
    gossip = GossipProtocol(registry=registry, own_url="http://localhost:9000")

    # Context dir
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "profile.md").write_text("# Test Profile\n")
    (ctx_dir / "skills.md").write_text("# Test Skills\n")
    (ctx_dir / "needs.md").write_text("# Test Needs\n")

    return {
        "agent_card": sample_agent_card,
        "did_manager": did_mgr,
        "event_bus": event_bus,
        "gossip": gossip,
        "data_dir": str(tmp_path),
    }


@pytest.fixture
def app(app_deps):
    """Create FastAPI app for testing."""
    return create_app(
        agent_card=app_deps["agent_card"],
        did_manager=app_deps["did_manager"],
        event_bus=app_deps["event_bus"],
        gossip=app_deps["gossip"],
        data_dir=app_deps["data_dir"],
    )


@pytest.fixture
async def client(app):
    """Async httpx test client."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "agent" in data
        assert "skills" in data

    async def test_health_includes_did(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert data["did"] is not None
        assert data["did"].startswith("did:key:z")

    async def test_health_includes_card_regenerating(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert data["card_regenerating"] is False


class TestCardEndpoint:
    async def test_card_returns_info(self, client):
        resp = await client.get("/card")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "skills" in data
        assert isinstance(data["skills"], list)

    async def test_well_known_agent_card(self, client):
        resp = await client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "skills" in data


class TestIdentityEndpoint:
    async def test_identity_returns_did(self, client):
        resp = await client.get("/identity")
        assert resp.status_code == 200
        data = resp.json()
        assert "did" in data
        assert "public_key" in data
        assert "signed_card" in data

    async def test_identity_signed_card_has_proof(self, client):
        resp = await client.get("/identity")
        data = resp.json()
        signed = data["signed_card"]
        assert "proof" in signed
        assert signed["proof"]["type"] == "Ed25519Signature2020"


class TestProfileEndpoint:
    async def test_get_profile(self, client):
        resp = await client.get("/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data
        assert "profile.md" in data["files"]
        assert "skills.md" in data["files"]
        assert "needs.md" in data["files"]

    async def test_update_profile(self, client):
        resp = await client.put(
            "/profile/skills.md",
            json={"content": "# Updated Skills\n- New skill\n"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["file"] == "skills.md"

    async def test_update_profile_invalid_file(self, client):
        resp = await client.put(
            "/profile/invalid.txt",
            json={"content": "test"},
        )
        data = resp.json()
        assert "error" in data


class TestGossipEndpoints:
    async def test_gossip_peers_get(self, client):
        resp = await client.get("/gossip/peers")
        assert resp.status_code == 200
        data = resp.json()
        assert "peers" in data

    async def test_gossip_peers_post(self, client):
        resp = await client.post("/gossip/peers", json={
            "source": "http://other:9001",
            "peers": [{"url": "http://new:9002"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "peers" in data

    async def test_gossip_stats(self, client):
        resp = await client.get("/gossip/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "rounds" in data


class TestEventsEndpoint:
    async def test_recent_events(self, client):
        resp = await client.get("/events/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
