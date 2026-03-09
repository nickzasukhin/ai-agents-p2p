"""Tests for A2AClient — card fetching, self-skip, TOFU identity."""

import json
import pytest
from src.a2a_client.client import A2AClient, DiscoveredAgent


def _card_json(name="Remote Agent", skills=None):
    """Helper to generate a valid agent card JSON response."""
    if skills is None:
        skills = [{"id": "s-0", "name": "Testing", "description": "Test skill",
                    "tags": ["test"], "examples": []}]
    return {
        "name": name,
        "description": f"Agent: {name}",
        "url": "http://remote:9000/",
        "version": "0.1.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": {},
        "skills": skills,
        "security": [],
    }


class TestFetchAgentCard:
    async def test_fetch_success(self, httpx_mock):
        httpx_mock.add_response(
            url="http://remote:9000/.well-known/agent-card.json",
            json=_card_json(),
        )
        # Mock identity endpoint (404 is ok)
        httpx_mock.add_response(url="http://remote:9000/identity", status_code=404)

        client = A2AClient(timeout=5.0, own_url="http://self:9000")
        result = await client.fetch_agent_card("http://remote:9000")
        assert result is not None
        assert result.card.name == "Remote Agent"
        assert isinstance(result, DiscoveredAgent)

    async def test_fetch_builds_skills_text(self, httpx_mock):
        httpx_mock.add_response(
            url="http://remote:9000/.well-known/agent-card.json",
            json=_card_json(skills=[
                {"id": "s-0", "name": "Python", "description": "Python dev",
                 "tags": [], "examples": []},
                {"id": "s-1", "name": "ML", "description": "Machine learning",
                 "tags": [], "examples": []},
            ]),
        )
        httpx_mock.add_response(url="http://remote:9000/identity", status_code=404)

        client = A2AClient(timeout=5.0, own_url="http://self:9000")
        result = await client.fetch_agent_card("http://remote:9000")
        assert "Python" in result.skills_text
        assert "ML" in result.skills_text

    async def test_fetch_unreachable_returns_none(self, httpx_mock):
        import httpx
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="http://dead:9000/.well-known/agent-card.json",
        )
        client = A2AClient(timeout=2.0, own_url="http://self:9000", retry_attempts=1)
        result = await client.fetch_agent_card("http://dead:9000")
        assert result is None

    async def test_skip_self(self, httpx_mock):
        client = A2AClient(timeout=5.0, own_url="http://self:9000")
        result = await client.fetch_agent_card("http://self:9000")
        assert result is None


class TestDiscoverAgents:
    async def test_discover_multiple(self, httpx_mock):
        for port in [9001, 9002]:
            httpx_mock.add_response(
                url=f"http://agent{port}:{port}/.well-known/agent-card.json",
                json=_card_json(name=f"Agent-{port}"),
            )
            httpx_mock.add_response(
                url=f"http://agent{port}:{port}/identity",
                status_code=404,
            )

        client = A2AClient(timeout=5.0, own_url="http://self:9000")
        agents = await client.discover_agents([
            f"http://agent{p}:{p}" for p in [9001, 9002]
        ])
        assert len(agents) == 2

    async def test_discover_partial_failure(self, httpx_mock):
        import httpx
        httpx_mock.add_response(
            url="http://good:9001/.well-known/agent-card.json",
            json=_card_json(name="Good"),
        )
        httpx_mock.add_response(url="http://good:9001/identity", status_code=404)
        httpx_mock.add_exception(
            httpx.ConnectError("refused"),
            url="http://bad:9002/.well-known/agent-card.json",
        )

        client = A2AClient(timeout=2.0, own_url="http://self:9000", retry_attempts=1)
        agents = await client.discover_agents(["http://good:9001", "http://bad:9002"])
        assert len(agents) == 1
        assert agents[0].card.name == "Good"
