"""Tests for Phase 12.5 — Global Search."""

import pytest
import httpx
import numpy as np

from a2a.types import AgentCard, AgentSkill, AgentCapabilities
from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry
from src.matching.engine import MatchingEngine
from src.a2a_client.client import DiscoveredAgent


# ── Unit Tests: MatchingEngine.search_agents ──────────────────

def _make_discovered_agent(url: str, name: str, description: str, skills: list[dict]) -> DiscoveredAgent:
    """Helper to create a DiscoveredAgent for testing."""
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
    )

    skills_text = "; ".join(s["name"] for s in skills)
    return DiscoveredAgent(
        url=url,
        card=card,
        skills_text=skills_text,
    )


class TestSearchEngine:
    @pytest.fixture(scope="class")
    def engine(self):
        """Shared matching engine."""
        return MatchingEngine()

    @pytest.fixture(scope="class")
    def test_agents(self):
        """Sample agents for search tests."""
        return [
            _make_discovered_agent(
                "http://agent1.example.com",
                "Python Expert",
                "Expert Python developer specializing in FastAPI and machine learning",
                [
                    {"name": "Python Development", "description": "FastAPI, Django, Flask", "tags": ["python"]},
                    {"name": "Machine Learning", "description": "TensorFlow, PyTorch", "tags": ["ml"]},
                ],
            ),
            _make_discovered_agent(
                "http://agent2.example.com",
                "UI Designer",
                "Creative UI/UX designer with experience in React and Figma",
                [
                    {"name": "UI Design", "description": "Figma, Sketch, Adobe XD", "tags": ["design"]},
                    {"name": "React Frontend", "description": "React, TypeScript, Tailwind", "tags": ["react"]},
                ],
            ),
            _make_discovered_agent(
                "http://agent3.example.com",
                "DevOps Engineer",
                "Infrastructure and deployment specialist with Kubernetes and Docker",
                [
                    {"name": "Kubernetes", "description": "K8s cluster management", "tags": ["k8s"]},
                    {"name": "Docker", "description": "Containerization and orchestration", "tags": ["docker"]},
                ],
            ),
        ]

    def test_search_returns_results(self, engine, test_agents):
        """Search should return results for a relevant query."""
        results = engine.search_agents("python developer", test_agents)
        assert len(results) > 0

    def test_search_result_structure(self, engine, test_agents):
        """Each result should have required fields."""
        results = engine.search_agents("python", test_agents)
        assert len(results) > 0
        for r in results:
            assert "agent_url" in r
            assert "agent_name" in r
            assert "description" in r
            assert "skills" in r
            assert "match_score" in r

    def test_search_scores_sorted(self, engine, test_agents):
        """Results should be sorted by match_score descending."""
        results = engine.search_agents("python machine learning", test_agents)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i]["match_score"] >= results[i + 1]["match_score"]

    def test_search_relevance(self, engine, test_agents):
        """Python query should rank Python agent higher than UI designer."""
        results = engine.search_agents("python fastapi backend", test_agents)
        assert len(results) > 0
        # Python Expert should score higher
        python_results = [r for r in results if "Python" in r["agent_name"]]
        design_results = [r for r in results if "Designer" in r["agent_name"]]
        if python_results and design_results:
            assert python_results[0]["match_score"] >= design_results[0]["match_score"]

    def test_search_empty_query(self, engine, test_agents):
        """Empty query should return empty results."""
        results = engine.search_agents("", test_agents)
        assert results == []

    def test_search_no_agents(self, engine):
        """Search with no agents should return empty results."""
        results = engine.search_agents("python", [])
        assert results == []

    def test_search_limit(self, engine, test_agents):
        """Limit parameter should cap results."""
        results = engine.search_agents("developer", test_agents, limit=1)
        assert len(results) <= 1

    def test_search_match_score_range(self, engine, test_agents):
        """Match scores should be between 0 and 1."""
        results = engine.search_agents("kubernetes docker", test_agents)
        for r in results:
            assert 0 <= r["match_score"] <= 1.0


# ── API Endpoint Tests ────────────────────────────────────────

@pytest.fixture
def search_app(tmp_path, sample_agent_card):
    """Create a FastAPI app for search testing."""
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
async def search_client(search_app):
    """Async httpx test client."""
    transport = httpx.ASGITransport(app=search_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSearchEndpoint:
    async def test_search_returns_200(self, search_client):
        """GET /search should return 200."""
        resp = await search_client.get("/search", params={"q": "python"})
        assert resp.status_code == 200

    async def test_search_response_structure(self, search_client):
        """Response should have query, results, and total fields."""
        resp = await search_client.get("/search", params={"q": "python"})
        data = resp.json()
        assert "query" in data
        assert "results" in data
        assert "total" in data
        assert data["query"] == "python"

    async def test_search_empty_query(self, search_client):
        """Empty query should return empty results."""
        resp = await search_client.get("/search", params={"q": ""})
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_search_no_query(self, search_client):
        """Missing query parameter should return empty results."""
        resp = await search_client.get("/search")
        data = resp.json()
        assert data["results"] == []

    async def test_search_limit_param(self, search_client):
        """Limit parameter should be accepted."""
        resp = await search_client.get("/search", params={"q": "test", "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] <= 5

    async def test_search_no_auth_required(self, tmp_path, sample_agent_card):
        """GET /search should work without auth (it's a GET = read-only)."""
        from src.agent.config import AgentConfig

        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        config = AgentConfig(api_token="secret-token")

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
            resp = await client.get("/search", params={"q": "python"})
            assert resp.status_code == 200
