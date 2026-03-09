"""Tests for Profile Builder — AgentCard generation with LLM mock."""

import json
import pytest
from unittest.mock import patch, MagicMock
from src.profile.builder import build_agent_card_from_context, _build_card_without_llm
from src.profile.mcp_reader import OwnerContext, OwnerCapability


def _make_context():
    return OwnerContext(
        capabilities=[
            OwnerCapability(name="Python Dev", description="Expert Python developer", category="skills"),
            OwnerCapability(name="ML Engineering", description="Machine learning", category="skills"),
        ],
        raw_text="# Skills\n- Python development\n- Machine learning\n",
    )


class TestBuildCardWithoutLLM:
    def test_returns_agent_card(self):
        ctx = _make_context()
        card = _build_card_without_llm(ctx, "TestAgent", "http://test:9000/")
        assert card.name == "TestAgent"
        assert card.url == "http://test:9000/"
        assert len(card.skills) == 2

    def test_skills_from_capabilities(self):
        ctx = _make_context()
        card = _build_card_without_llm(ctx, "TestAgent", "http://test:9000/")
        skill_names = [s.name for s in card.skills]
        assert "Python Dev" in skill_names
        assert "ML Engineering" in skill_names


class TestBuildCardWithLLM:
    def test_no_api_key_falls_back(self):
        ctx = _make_context()
        card = build_agent_card_from_context(
            ctx, "TestAgent", "http://test:9000/",
            openai_api_key="",
        )
        assert card.name == "TestAgent"
        assert len(card.skills) >= 1

    def test_llm_builds_card(self):
        llm_response = json.dumps({
            "name": "AI Expert",
            "description": "An AI specialist",
            "skills": [
                {"id": "s-0", "name": "Python", "description": "Python dev", "tags": ["py"]},
                {"id": "s-1", "name": "ML", "description": "ML engineering", "tags": ["ml"]},
            ],
        })
        mock_llm = MagicMock()
        mock_llm.chat.return_value = llm_response
        mock_llm.name = "openai"
        mock_llm.model = "gpt-4o-mini"

        ctx = _make_context()
        card = build_agent_card_from_context(
            ctx, "TestAgent", "http://test:9000/",
            llm=mock_llm,
        )
        assert card.name == "AI Expert"
        assert len(card.skills) == 2

    def test_llm_invalid_json_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "not valid json!!!"
        mock_llm.name = "openai"
        mock_llm.model = "gpt-4o-mini"

        ctx = _make_context()
        card = build_agent_card_from_context(
            ctx, "TestAgent", "http://test:9000/",
            llm=mock_llm,
        )
        assert card.name == "TestAgent"
        assert len(card.skills) >= 1

    def test_card_url_matches_argument(self):
        ctx = _make_context()
        card = _build_card_without_llm(ctx, "X", "http://custom:1234/")
        assert card.url == "http://custom:1234/"
