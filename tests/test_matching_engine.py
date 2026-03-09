"""Tests for MatchingEngine — bidirectional needs↔skills matching."""

import pytest
from a2a.types import AgentCard, AgentSkill, AgentCapabilities
from src.a2a_client.client import DiscoveredAgent
from src.matching.engine import MatchingEngine

pytestmark = pytest.mark.slow


def _make_agent(name, skills_data, url="http://test:9000"):
    """Helper to create a DiscoveredAgent with given skills."""
    skills = [
        AgentSkill(id=f"s-{i}", name=s["name"], description=s["desc"],
                   tags=s.get("tags", []), examples=[])
        for i, s in enumerate(skills_data)
    ]
    card = AgentCard(
        name=name,
        description=f"Agent: {name}",
        url=url,
        version="0.1.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(),
        skills=skills,
        security=[],
    )
    skills_text = " ".join(f"{s.name}: {s.description}" for s in skills)
    return DiscoveredAgent(url=url, card=card, skills_text=skills_text)


class TestMatchingEngine:
    def test_find_matches_empty_agents(self, embedding_engine):
        engine = MatchingEngine(embedding_engine=embedding_engine)
        matches = engine.find_matches("I need a Python developer", [])
        assert matches == []

    def test_find_matches_returns_results(self, embedding_engine):
        engine = MatchingEngine(embedding_engine=embedding_engine, threshold=0.2)
        context = """--- needs.md ---
# Needs
- UI/UX Designer for web dashboard
- Machine learning engineer
"""
        agent = _make_agent("Designer", [
            {"name": "UI Design", "desc": "Expert in web UI and UX design"},
            {"name": "Figma", "desc": "Professional Figma designer"},
        ])
        matches = engine.find_matches(context, [agent])
        assert len(matches) >= 1
        assert matches[0].agent_name == "Designer"

    def test_find_matches_sorted_by_score(self, embedding_engine):
        engine = MatchingEngine(embedding_engine=embedding_engine, threshold=0.2)
        context = """--- needs.md ---
# Needs
- Python developer for backend API
"""
        agents = [
            _make_agent("Chef", [
                {"name": "Cooking", "desc": "Italian cuisine chef"},
            ], url="http://chef:9000"),
            _make_agent("Dev", [
                {"name": "Python", "desc": "Expert Python FastAPI developer"},
            ], url="http://dev:9000"),
        ]
        matches = engine.find_matches(context, agents)
        if len(matches) >= 2:
            assert matches[0].overall_score >= matches[1].overall_score

    def test_find_matches_above_threshold(self, embedding_engine):
        engine = MatchingEngine(embedding_engine=embedding_engine, threshold=0.3)
        context = "I need a Python developer"
        agent = _make_agent("Dev", [
            {"name": "Python", "desc": "Python development"},
        ])
        matches = engine.find_matches(context, [agent])
        for m in matches:
            assert m.overall_score >= 0.3

    def test_agent_match_has_skill_matches(self, embedding_engine):
        engine = MatchingEngine(embedding_engine=embedding_engine, threshold=0.2)
        context = """--- needs.md ---
# Needs
- Frontend React developer
"""
        agent = _make_agent("Frontend", [
            {"name": "React Development", "desc": "Expert React developer"},
        ])
        matches = engine.find_matches(context, [agent])
        if matches:
            assert len(matches[0].skill_matches) > 0
            sm = matches[0].skill_matches[0]
            assert hasattr(sm, "similarity")
            assert hasattr(sm, "direction")
