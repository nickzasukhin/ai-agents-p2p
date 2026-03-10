"""Tests for Phase 12.1 — Seed Nodes + Add Peer by URL."""

import pytest
import httpx

from src.agent.config import AgentConfig, DEFAULT_SEED_NODES
from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry


# ── Seed Node Config Tests ──────────────────────────────────────

class TestSeedNodeConfig:
    def test_default_seed_nodes_not_empty(self):
        """DEFAULT_SEED_NODES should contain at least one production URL."""
        assert len(DEFAULT_SEED_NODES) >= 1
        assert "agents.devpunks.io" in DEFAULT_SEED_NODES[0]

    def test_config_has_seed_nodes_default(self):
        """AgentConfig should have seed_nodes with default values."""
        config = AgentConfig()
        assert config.seed_nodes == DEFAULT_SEED_NODES
        assert config.skip_seeds is False

    def test_config_skip_seeds(self):
        """skip_seeds=True should be respected."""
        config = AgentConfig(skip_seeds=True)
        assert config.skip_seeds is True

    def test_config_custom_seed_nodes(self):
        """Custom seed nodes should override defaults."""
        custom = ["https://custom-seed.example.com"]
        config = AgentConfig(seed_nodes=custom)
        assert config.seed_nodes == custom

    def test_config_seed_nodes_from_json_string(self):
        """seed_nodes should parse JSON array strings (for Docker env)."""
        config = AgentConfig(seed_nodes='["https://a.com", "https://b.com"]')
        assert config.seed_nodes == ["https://a.com", "https://b.com"]

    def test_config_seed_nodes_from_comma_string(self):
        """seed_nodes should parse comma-separated strings."""
        config = AgentConfig(seed_nodes="https://a.com, https://b.com")
        assert config.seed_nodes == ["https://a.com", "https://b.com"]

    def test_config_empty_seed_nodes(self):
        """Empty seed_nodes should result in empty list."""
        config = AgentConfig(seed_nodes=[])
        assert config.seed_nodes == []


# ── Seed Node Injection Tests ───────────────────────────────────

class TestSeedNodeInjection:
    def test_seeds_injected_when_no_peers(self, tmp_path):
        """Seeds should be added to registry when no peers configured."""
        config = AgentConfig(
            seed_nodes=["https://seed1.example.com", "https://seed2.example.com"],
            skip_seeds=False,
        )
        own_url = "http://localhost:9000"

        registry = StaticRegistry(registry_path=tmp_path / "registry.json")
        registry.load()

        # Simulate seed injection logic from run_node.py
        if not config.skip_seeds and config.seed_nodes and len(registry) == 0:
            for seed_url in config.seed_nodes:
                seed_clean = seed_url.rstrip("/")
                if seed_clean != own_url.rstrip("/"):
                    registry.add(seed_clean)

        assert len(registry) == 2

    def test_seeds_not_injected_when_peers_exist(self, tmp_path):
        """Seeds should NOT be added when peers already configured."""
        config = AgentConfig(
            seed_nodes=["https://seed1.example.com"],
            skip_seeds=False,
        )
        own_url = "http://localhost:9000"

        registry = StaticRegistry(registry_path=tmp_path / "registry.json")
        registry.load()
        registry.add("http://existing-peer:9001")

        # Simulate seed injection logic — should skip because registry not empty
        if not config.skip_seeds and config.seed_nodes and len(registry) == 0:
            for seed_url in config.seed_nodes:
                seed_clean = seed_url.rstrip("/")
                if seed_clean != own_url.rstrip("/"):
                    registry.add(seed_clean)

        # Only the existing peer should be there
        assert len(registry) == 1

    def test_seeds_not_injected_when_skip_seeds(self, tmp_path):
        """Seeds should NOT be added when skip_seeds=True."""
        config = AgentConfig(
            seed_nodes=["https://seed1.example.com"],
            skip_seeds=True,
        )
        own_url = "http://localhost:9000"

        registry = StaticRegistry(registry_path=tmp_path / "registry.json")
        registry.load()

        if not config.skip_seeds and config.seed_nodes and len(registry) == 0:
            for seed_url in config.seed_nodes:
                seed_clean = seed_url.rstrip("/")
                if seed_clean != own_url.rstrip("/"):
                    registry.add(seed_clean)

        assert len(registry) == 0

    def test_seeds_skip_self_url(self, tmp_path):
        """Seeds should not add own URL."""
        config = AgentConfig(
            seed_nodes=["https://agents.devpunks.io", "http://localhost:9000"],
            skip_seeds=False,
        )
        own_url = "http://localhost:9000"

        registry = StaticRegistry(registry_path=tmp_path / "registry.json")
        registry.load()

        if not config.skip_seeds and config.seed_nodes and len(registry) == 0:
            for seed_url in config.seed_nodes:
                seed_clean = seed_url.rstrip("/")
                if seed_clean != own_url.rstrip("/"):
                    registry.add(seed_clean)

        assert len(registry) == 1  # Only the devpunks one


# ── POST /peers/add Endpoint Tests ─────────────────────────────

@pytest.fixture
def app_with_own_url(tmp_path, sample_agent_card):
    """Create a FastAPI app with own_url set for peer add testing."""
    did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
    did_mgr.init()

    event_bus = EventBus(max_buffer=20)
    registry = StaticRegistry(registry_path=tmp_path / "registry.json")
    gossip = GossipProtocol(registry=registry, own_url="http://localhost:9000")

    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "profile.md").write_text("# Test\n")
    (ctx_dir / "skills.md").write_text("# Skills\n")
    (ctx_dir / "needs.md").write_text("# Needs\n")

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
async def peer_client(app_with_own_url):
    """Async httpx test client for peer tests."""
    transport = httpx.ASGITransport(app=app_with_own_url)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAddPeerEndpoint:
    async def test_add_peer_missing_url(self, peer_client):
        """POST /peers/add without URL should return 400."""
        resp = await peer_client.post("/peers/add", json={})
        assert resp.status_code == 400
        assert "Missing" in resp.json()["error"]

    async def test_add_peer_empty_url(self, peer_client):
        """POST /peers/add with empty URL should return 400."""
        resp = await peer_client.post("/peers/add", json={"url": ""})
        assert resp.status_code == 400

    async def test_add_peer_self_rejection(self, peer_client):
        """POST /peers/add with own URL should return 400."""
        resp = await peer_client.post(
            "/peers/add", json={"url": "http://localhost:9000"}
        )
        assert resp.status_code == 400
        assert "self" in resp.json()["error"].lower()

    async def test_add_peer_invalid_url_format(self, peer_client):
        """POST /peers/add with invalid URL should return 400."""
        resp = await peer_client.post(
            "/peers/add", json={"url": "not-a-valid-url"}
        )
        assert resp.status_code == 400
        assert "Invalid URL" in resp.json()["error"]

    async def test_add_peer_unreachable(self, peer_client):
        """POST /peers/add with unreachable URL should return 502."""
        resp = await peer_client.post(
            "/peers/add", json={"url": "https://nonexistent.invalid.example.com"}
        )
        assert resp.status_code in (502, 404)

    async def test_add_peer_requires_auth_when_token_set(self, tmp_path, sample_agent_card):
        """POST /peers/add should require auth when API token is set."""
        from src.agent.config import AgentConfig

        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        config = AgentConfig(api_token="test-secret-token")

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
            # Without token — should be rejected
            resp = await client.post("/peers/add", json={"url": "https://example.com"})
            assert resp.status_code == 401

            # With token — should pass auth (may fail on fetch, but not on auth)
            resp = await client.post(
                "/peers/add",
                json={"url": "https://example.com"},
                headers={"Authorization": "Bearer test-secret-token"},
            )
            assert resp.status_code != 401
            assert resp.status_code != 403
