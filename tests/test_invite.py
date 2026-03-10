"""Tests for Phase 12.2 — Invite Links."""

import pytest
import httpx

from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry


@pytest.fixture
def invite_app(tmp_path, sample_agent_card):
    """Create a FastAPI app for invite link testing."""
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
async def invite_client(invite_app):
    """Async httpx test client for invite tests."""
    app, _ = invite_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── GET /invite/data Tests ───────────────────────────────────

class TestInviteData:
    async def test_invite_data_returns_200(self, invite_client):
        """GET /invite/data should return 200 OK."""
        resp = await invite_client.get("/invite/data")
        assert resp.status_code == 200

    async def test_invite_data_has_required_fields(self, invite_client):
        """GET /invite/data should contain agent_name, description, skills, agent_url, did."""
        resp = await invite_client.get("/invite/data")
        data = resp.json()
        assert "agent_name" in data
        assert "description" in data
        assert "skills" in data
        assert "agent_url" in data
        assert "did" in data

    async def test_invite_data_agent_name(self, invite_client):
        """Agent name should match the configured card."""
        resp = await invite_client.get("/invite/data")
        data = resp.json()
        assert data["agent_name"] == "Test Agent"

    async def test_invite_data_skills_structure(self, invite_client):
        """Skills should be a list of objects with name, description, tags."""
        resp = await invite_client.get("/invite/data")
        data = resp.json()
        skills = data["skills"]
        assert isinstance(skills, list)
        assert len(skills) == 2  # sample_agent_card has 2 skills
        for skill in skills:
            assert "name" in skill
            assert "description" in skill
            assert "tags" in skill

    async def test_invite_data_skills_content(self, invite_client):
        """Skills should contain correct data from agent card."""
        resp = await invite_client.get("/invite/data")
        data = resp.json()
        skill_names = [s["name"] for s in data["skills"]]
        assert "Python Development" in skill_names
        assert "Machine Learning" in skill_names

    async def test_invite_data_agent_url(self, invite_client):
        """agent_url should be the configured own_url."""
        resp = await invite_client.get("/invite/data")
        data = resp.json()
        assert data["agent_url"] == "http://localhost:9000"

    async def test_invite_data_has_did(self, invite_app, invite_client):
        """DID should be populated from did_manager."""
        _, did_mgr = invite_app
        resp = await invite_client.get("/invite/data")
        data = resp.json()
        assert data["did"] == did_mgr.did
        assert data["did"].startswith("did:key:")

    async def test_invite_data_description(self, invite_client):
        """Description should match agent card."""
        resp = await invite_client.get("/invite/data")
        data = resp.json()
        assert data["description"] == "A test agent for unit tests"


# ── GET /invite HTML Tests ────────────────────────────────────

class TestInvitePage:
    async def test_invite_returns_200(self, invite_client):
        """GET /invite should return 200 OK."""
        resp = await invite_client.get("/invite")
        assert resp.status_code == 200

    async def test_invite_returns_html(self, invite_client):
        """GET /invite should return HTML content type."""
        resp = await invite_client.get("/invite")
        assert "text/html" in resp.headers["content-type"]

    async def test_invite_contains_agent_name(self, invite_client):
        """HTML should contain the agent name."""
        resp = await invite_client.get("/invite")
        assert "Test Agent" in resp.text

    async def test_invite_contains_description(self, invite_client):
        """HTML should contain the agent description."""
        resp = await invite_client.get("/invite")
        assert "A test agent for unit tests" in resp.text

    async def test_invite_contains_skills(self, invite_client):
        """HTML should contain skill names."""
        resp = await invite_client.get("/invite")
        html = resp.text
        assert "Python Development" in html
        assert "Machine Learning" in html

    async def test_invite_contains_og_tags(self, invite_client):
        """HTML should contain Open Graph meta tags."""
        resp = await invite_client.get("/invite")
        html = resp.text
        assert 'property="og:title"' in html
        assert 'property="og:description"' in html
        assert 'property="og:url"' in html
        assert 'property="og:type"' in html

    async def test_invite_contains_twitter_tags(self, invite_client):
        """HTML should contain Twitter Card meta tags."""
        resp = await invite_client.get("/invite")
        html = resp.text
        assert 'name="twitter:card"' in html
        assert 'name="twitter:title"' in html
        assert 'name="twitter:description"' in html

    async def test_invite_og_title_format(self, invite_client):
        """OG title should include agent name and DevPunks."""
        resp = await invite_client.get("/invite")
        html = resp.text
        assert "Test Agent" in html
        assert "DevPunks" in html

    async def test_invite_contains_agent_url(self, invite_client):
        """HTML should contain the agent URL."""
        resp = await invite_client.get("/invite")
        assert "http://localhost:9000" in resp.text

    async def test_invite_contains_agent_card_link(self, invite_client):
        """HTML should link to the agent card."""
        resp = await invite_client.get("/invite")
        assert "/.well-known/agent-card.json" in resp.text

    async def test_invite_devpunks_branding(self, invite_client):
        """HTML should have DevPunks branding and accent color."""
        resp = await invite_client.get("/invite")
        html = resp.text
        assert "DevPunks" in html
        assert "#E50051" in html  # Accent color

    async def test_invite_dark_theme(self, invite_client):
        """HTML should use dark theme colors."""
        resp = await invite_client.get("/invite")
        html = resp.text
        assert "#0a0a0f" in html  # Dark background

    async def test_invite_html_escaping(self, tmp_path, sample_agent_card):
        """HTML should properly escape special characters in agent data."""
        from a2a.types import AgentCard, AgentSkill, AgentCapabilities

        # Create card with HTML-dangerous characters
        xss_card = AgentCard(
            name='Agent <script>alert("xss")</script>',
            description='Test & "quotes" <b>bold</b>',
            url="http://localhost:9000/",
            version="0.1.0",
            defaultInputModes=["text"],
            defaultOutputModes=["text"],
            capabilities=AgentCapabilities(),
            skills=[
                AgentSkill(
                    id="skill-0",
                    name='<img onerror="alert(1)">',
                    description="Test skill",
                    tags=["test"],
                    examples=[],
                ),
            ],
            security=[],
        )

        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        registry = StaticRegistry(registry_path=tmp_path / "registry.json")
        gossip = GossipProtocol(registry=registry, own_url="http://localhost:9000")

        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()
        (ctx_dir / "profile.md").write_text("# Test\n")

        app = create_app(
            agent_card=xss_card,
            did_manager=did_mgr,
            event_bus=event_bus,
            gossip=gossip,
            data_dir=str(tmp_path),
            own_url="http://localhost:9000",
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/invite")
            html = resp.text
            # Should NOT contain raw script tag
            assert "<script>" not in html
            # Should contain escaped version
            assert "&lt;script&gt;" in html
            # Should NOT contain raw onerror
            assert 'onerror="alert' not in html


# ── Invite Endpoints Are Public (No Auth Required) ────────────

class TestInviteAuth:
    async def test_invite_page_no_auth_required(self, tmp_path, sample_agent_card):
        """GET /invite should work without auth even when API token is set."""
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
            # /invite should work without token (it's a GET = read-only)
            resp = await client.get("/invite")
            assert resp.status_code == 200

            # /invite/data should also work without token (GET = read-only)
            resp = await client.get("/invite/data")
            assert resp.status_code == 200
