"""Tests for public profile page endpoint."""

import pytest
import httpx

from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry


@pytest.fixture
def profile_app(tmp_path, sample_agent_card):
    """Create a FastAPI app for profile page testing."""
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
    return app, did_mgr


@pytest.fixture
async def profile_client(profile_app):
    """Async httpx test client for profile tests."""
    app, _ = profile_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── GET /profile HTML Page Tests ───────────────────────────────

class TestProfilePage:
    async def test_profile_returns_200(self, profile_client):
        """GET /profile should return 200 OK."""
        resp = await profile_client.get("/profile")
        assert resp.status_code == 200

    async def test_profile_returns_html(self, profile_client):
        """GET /profile should return HTML content type."""
        resp = await profile_client.get("/profile")
        assert "text/html" in resp.headers["content-type"]

    async def test_profile_contains_agent_name(self, profile_client):
        """Profile page should contain the agent name."""
        resp = await profile_client.get("/profile")
        assert "Test Agent" in resp.text

    async def test_profile_contains_description(self, profile_client):
        """Profile page should contain the agent description."""
        resp = await profile_client.get("/profile")
        assert "A test agent for unit tests" in resp.text

    async def test_profile_contains_skills(self, profile_client):
        """Profile page should contain skill names."""
        resp = await profile_client.get("/profile")
        assert "Python Development" in resp.text
        assert "Machine Learning" in resp.text

    async def test_profile_contains_version(self, profile_client):
        """Profile page should contain agent version."""
        resp = await profile_client.get("/profile")
        assert "0.1.0" in resp.text

    async def test_profile_contains_did(self, profile_client):
        """Profile page should contain truncated DID."""
        resp = await profile_client.get("/profile")
        assert "did:key:" in resp.text

    async def test_profile_contains_agent_url(self, profile_client):
        """Profile page should contain agent URL."""
        resp = await profile_client.get("/profile")
        assert "http://localhost:9000" in resp.text

    async def test_profile_og_tags(self, profile_client):
        """Profile page should have Open Graph meta tags."""
        resp = await profile_client.get("/profile")
        html = resp.text
        assert 'og:type' in html
        assert 'og:title' in html
        assert 'og:description' in html
        assert 'og:url' in html
        assert 'og:site_name' in html

    async def test_profile_twitter_card(self, profile_client):
        """Profile page should have Twitter card meta tags."""
        resp = await profile_client.get("/profile")
        html = resp.text
        assert 'twitter:card' in html
        assert 'twitter:title' in html
        assert 'twitter:description' in html

    async def test_profile_og_type_is_profile(self, profile_client):
        """OG type should be 'profile'."""
        resp = await profile_client.get("/profile")
        assert 'content="profile"' in resp.text

    async def test_profile_has_json_card_link(self, profile_client):
        """Profile should link to JSON agent card."""
        resp = await profile_client.get("/profile")
        assert ".well-known/agent-card.json" in resp.text

    async def test_profile_devpunks_branding(self, profile_client):
        """Profile should have DevPunks branding."""
        resp = await profile_client.get("/profile")
        assert "DevPunks" in resp.text

    async def test_profile_dark_theme(self, profile_client):
        """Profile should use dark theme (dark background)."""
        resp = await profile_client.get("/profile")
        assert "#0a0a0f" in resp.text

    async def test_profile_html_escaping(self, profile_app, tmp_path):
        """Profile page should properly escape HTML entities."""
        from a2a.types import AgentCard, AgentCapabilities
        app, did_mgr = profile_app

        # Create app with XSS-attempt agent name
        xss_card = AgentCard(
            name='<script>alert("xss")</script>',
            description='Test <b>bold</b> description',
            url="http://localhost:9000/",
            version="0.1.0",
            defaultInputModes=["text"],
            defaultOutputModes=["text"],
            capabilities=AgentCapabilities(),
            skills=[],
            security=[],
        )
        xss_app = create_app(
            agent_card=xss_card,
            did_manager=did_mgr,
            event_bus=EventBus(max_buffer=20),
            gossip=GossipProtocol(
                registry=StaticRegistry(registry_path=tmp_path / "r2.json"),
                own_url="http://localhost:9000",
            ),
            data_dir=str(tmp_path),
            own_url="http://localhost:9000",
        )
        transport = httpx.ASGITransport(app=xss_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/profile")
            assert "<script>" not in resp.text
            assert "&lt;script&gt;" in resp.text


class TestProfileContextButtons:
    """Test context-aware action buttons based on visitor cookies."""

    async def test_anonymous_sees_signup(self, profile_client):
        """Anonymous visitor should see 'Sign up to connect' button."""
        resp = await profile_client.get("/profile")
        assert "Sign up to connect" in resp.text

    async def test_anonymous_no_negotiate(self, profile_client):
        """Anonymous visitor should not see negotiate button."""
        resp = await profile_client.get("/profile")
        assert "doNegotiate" not in resp.text

    async def test_owner_sees_manage(self, profile_client):
        """Owner (matching agent_url cookie) should see 'Manage Agent' button."""
        resp = await profile_client.get(
            "/profile",
            cookies={"agent_url": "http://localhost:9000", "agent_token": "test-token"},
        )
        assert "Manage Agent" in resp.text
        assert "/app" in resp.text

    async def test_owner_no_negotiate(self, profile_client):
        """Owner should not see negotiate button."""
        resp = await profile_client.get(
            "/profile",
            cookies={"agent_url": "http://localhost:9000", "agent_token": "test-token"},
        )
        assert "doNegotiate" not in resp.text

    async def test_authenticated_nonowner_sees_negotiate(self, profile_client):
        """Authenticated non-owner should see negotiate button."""
        resp = await profile_client.get(
            "/profile",
            cookies={"agent_url": "http://other-agent:9001", "agent_token": "other-token"},
        )
        assert "Negotiate" in resp.text
        assert "doNegotiate" in resp.text

    async def test_authenticated_nonowner_no_manage(self, profile_client):
        """Authenticated non-owner should NOT see manage button."""
        resp = await profile_client.get(
            "/profile",
            cookies={"agent_url": "http://other-agent:9001", "agent_token": "other-token"},
        )
        assert "Manage Agent" not in resp.text


class TestProfileDataEndpoint:
    """Test that the renamed /profile/data endpoint still works."""

    async def test_profile_data_returns_200(self, profile_client):
        """GET /profile/data should return 200 OK."""
        resp = await profile_client.get("/profile/data")
        assert resp.status_code == 200

    async def test_profile_data_returns_json(self, profile_client):
        """GET /profile/data should return JSON."""
        resp = await profile_client.get("/profile/data")
        data = resp.json()
        assert "files" in data
        assert "profile.md" in data["files"]
