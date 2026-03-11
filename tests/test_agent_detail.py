"""Tests for Phase 13.2 — Agent Detail Endpoint."""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field

from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentProvider
from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry
from src.a2a_client.client import DiscoveredAgent
from src.matching.engine import AgentMatch, SkillNeedMatch, ScoreBreakdown


def _make_agent(url: str, name: str, description: str, skills: list[dict],
                did: str = "", verified: bool = False) -> DiscoveredAgent:
    """Create a DiscoveredAgent for testing."""
    card = AgentCard(
        name=name,
        description=description,
        url=url,
        version="0.1.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id=f"skill-{i}",
                name=s["name"],
                description=s.get("description", s["name"]),
                tags=s.get("tags", []),
                examples=[],
            )
            for i, s in enumerate(skills)
        ],
        security=[],
        provider=AgentProvider(organization="TestOrg", url=url),
    )
    return DiscoveredAgent(url=url, card=card, skills_text="; ".join(s["name"] for s in skills),
                           did=did, verified=verified)


def _make_match(agent_url: str, agent_name: str, score: float = 0.85,
                mutual: bool = True) -> AgentMatch:
    """Create an AgentMatch for testing."""
    skill_matches = [
        SkillNeedMatch(
            our_text="Need Python dev",
            their_text="Python Development",
            similarity=0.92,
            direction="we_need_they_offer",
        ),
    ]
    if mutual:
        skill_matches.append(SkillNeedMatch(
            our_text="Python Development",
            their_text="Need backend dev",
            similarity=0.88,
            direction="they_need_we_offer",
        ))

    return AgentMatch(
        agent_url=agent_url,
        agent_name=agent_name,
        overall_score=score,
        skill_matches=skill_matches,
        their_skills_text="Python; FastAPI",
        their_description="A great agent",
        score_breakdown=ScoreBreakdown(
            embedding=0.9,
            availability=0.0,
            history=0.0,
            tags=0.8,
            freshness=1.0,
            weighted_total=0.85,
            weights={"embedding": 0.7, "tags": 0.3},
        ),
    )


@dataclass
class FakeDiscoveryState:
    discovered_agents: dict = field(default_factory=dict)


class FakeDiscoveryLoop:
    def __init__(self, agents: dict = None, matches: list = None):
        self.state = FakeDiscoveryState(discovered_agents=agents or {})
        self._matches = matches or []

    def get_matches(self):
        return self._matches


@pytest.fixture
def detail_app(tmp_path, sample_agent_card):
    """Create a FastAPI app with a fake discovery loop for detail testing."""
    did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
    did_mgr.init()

    event_bus = EventBus(max_buffer=20)
    registry = StaticRegistry(registry_path=tmp_path / "registry.json")
    gossip = GossipProtocol(registry=registry, own_url="http://localhost:9000")

    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "profile.md").write_text("# Test\n")

    agent_a = _make_agent(
        "http://agent-a.example.com", "Agent Alpha", "Alpha does Python",
        [{"name": "Python", "description": "Expert Python", "tags": ["python", "backend"]}],
        did="did:key:abc123", verified=True,
    )
    agent_b = _make_agent(
        "http://agent-b.example.com", "Agent Beta", "Beta does React",
        [{"name": "React", "description": "React frontend", "tags": ["react", "frontend"]}],
    )

    match_a = _make_match("http://agent-a.example.com", "Agent Alpha")

    fake_loop = FakeDiscoveryLoop(
        agents={"http://agent-a.example.com": agent_a, "http://agent-b.example.com": agent_b},
        matches=[match_a],
    )

    app = create_app(
        agent_card=sample_agent_card,
        did_manager=did_mgr,
        event_bus=event_bus,
        gossip=gossip,
        data_dir=str(tmp_path),
        own_url="http://localhost:9000",
        discovery_loop=fake_loop,
    )
    return app


@pytest.fixture
async def detail_client(detail_app):
    """Async httpx test client."""
    transport = httpx.ASGITransport(app=detail_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAgentDetailEndpoint:
    async def test_no_url_returns_400(self, detail_client):
        """Missing url param should return 400."""
        resp = await detail_client.get("/discovery/agent")
        assert resp.status_code == 400
        assert "url parameter required" in resp.json()["error"]

    async def test_empty_url_returns_400(self, detail_client):
        """Empty url param should return 400."""
        resp = await detail_client.get("/discovery/agent", params={"url": ""})
        assert resp.status_code == 400

    async def test_not_found_returns_404(self, detail_client):
        """Unknown agent url should return 404."""
        resp = await detail_client.get("/discovery/agent", params={"url": "http://unknown.example.com"})
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"].lower()

    async def test_found_agent_returns_full_data(self, detail_client):
        """Known agent should return full details."""
        resp = await detail_client.get("/discovery/agent", params={"url": "http://agent-a.example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "Agent Alpha"
        assert data["description"] == "Alpha does Python"
        assert data["did"] == "did:key:abc123"
        assert data["verified"] is True
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "Python"
        assert data["skills"][0]["tags"] == ["python", "backend"]
        assert data["provider"]["organization"] == "TestOrg"

    async def test_found_agent_with_match_data(self, detail_client):
        """Agent with match should include match analysis."""
        resp = await detail_client.get("/discovery/agent", params={"url": "http://agent-a.example.com"})
        data = resp.json()
        assert data["match"] is not None
        assert data["match"]["overall_score"] == 0.85
        assert data["match"]["is_mutual"] is True
        assert data["match"]["score_breakdown"] is not None
        assert len(data["match"]["skill_matches"]) == 2
        directions = {sm["direction"] for sm in data["match"]["skill_matches"]}
        assert "we_need_they_offer" in directions
        assert "they_need_we_offer" in directions

    async def test_found_agent_without_match(self, detail_client):
        """Agent without match should have match=null."""
        resp = await detail_client.get("/discovery/agent", params={"url": "http://agent-b.example.com"})
        data = resp.json()
        assert data["agent_name"] == "Agent Beta"
        assert data["match"] is None

    async def test_trailing_slash_normalization(self, detail_client):
        """URL with trailing slash should still find the agent."""
        resp = await detail_client.get("/discovery/agent", params={"url": "http://agent-a.example.com/"})
        assert resp.status_code == 200
        assert resp.json()["agent_name"] == "Agent Alpha"
